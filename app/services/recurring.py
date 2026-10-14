from datetime import date, timedelta
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from ..models.recurring import RecurringTransaction
from ..models.utils import utc_now
from ..repositories.recurring import RecurringRepository
from ..models.transaction import PostingSide
from ..schemas.recurring import RecurringCreate, RecurringPostingData, RecurringRead, RecurringUpdate
from ..schemas.transaction import PostingCreate, TransactionCreate
from . import schedule
from .account import AccountService
from .simple import simple_postings
from .transaction import TransactionService
from .validation import validation_message


# One run records at most this many missed occurrences of a rule (a daily rule left for a year).
MAX_PER_RUN = 400
MAX_RULES = 100
ORIGIN = "recurring"


class RecurringService:
    def __init__(self, repo: RecurringRepository, accounts: AccountService, transactions: TransactionService):
        self.repo = repo
        self.accounts = accounts
        self.transactions = transactions

    def _to_read(self, rule: RecurringTransaction, rows: dict | None = None) -> RecurringRead:
        rows = self.repo.postings() if rows is None else rows
        read = RecurringRead.model_validate(rule, from_attributes=True)
        read.postings = [
            RecurringPostingData(account=p.account, side=PostingSide(p.side), amount=p.amount, value=p.value)
            for p in rows.get(rule.rid, [])
        ]
        return read

    def list(self) -> list[RecurringRead]:
        rows = self.repo.postings()
        return [self._to_read(r, rows) for r in self.repo.list()]

    def read(self, rid: UUID) -> RecurringRead | None:
        rule = self.repo.read(rid)
        return self._to_read(rule) if rule else None

    def _transaction(self, rule_like, day: date) -> TransactionCreate:
        if rule_like.postings:
            return TransactionCreate(
                date=day, payee=rule_like.payee, comment=rule_like.comment, currency=rule_like.currency,
                postings=[
                    PostingCreate(account=p.account, side=p.side, amount=p.amount, value=p.value)
                    for p in rule_like.postings
                ],
            )
        currency, postings = simple_postings(
            self.accounts, rule_like.amount, rule_like.received_amount, rule_like.from_account, rule_like.to_account
        )
        return TransactionCreate(
            date=day, payee=rule_like.payee, comment=rule_like.comment, currency=currency, postings=postings
        )

    @staticmethod
    def _rows(data) -> list[dict]:
        return [
            {"account": p.account, "side": p.side.value, "amount": p.amount, "value": p.value}
            for p in data.postings
        ]

    def as_transaction(self, rule: RecurringRead) -> TransactionCreate:
        """The transaction a rule records (on its start date): its currency and postings, for showing it."""
        return self._transaction(rule, rule.start_date)

    def _check(self, data: RecurringCreate | RecurringUpdate) -> None:
        """Refuse a rule that could never be recorded (same checks as recording it by hand)."""
        self.transactions.validate(self._transaction(data, data.start_date))

    def create(self, data: RecurringCreate) -> RecurringRead:
        if len(self.repo.list()) >= MAX_RULES:
            raise ValueError(f"you can have at most {MAX_RULES} recurring transactions!")
        self._check(data)
        rule = RecurringTransaction(
            **data.model_dump(exclude={"postings"}), user=self.repo.uid, next_date=data.start_date
        )
        self.repo.add(rule)
        self.repo.set_postings(rule.rid, self._rows(data))
        self.repo.db.commit()
        self.repo.db.refresh(rule)
        return self._to_read(rule)

    def update(self, rid: UUID, data: RecurringUpdate) -> RecurringRead | None:
        rule = self.repo.read(rid)
        if rule is None:
            return None
        self._check(data)
        for field, value in data.model_dump(exclude={"postings"}).items():
            setattr(rule, field, value)
        self.repo.set_postings(rule.rid, self._rows(data))
        # Carry on after the last occurrence that was recorded (or from the start if none was yet).
        rule.next_date = (
            schedule.first_after(rule.start_date, rule.frequency, rule.every, rule.last_date)
            if rule.last_date
            else rule.start_date
        )
        rule.last_error = None
        if rule.end_date is not None and rule.next_date > rule.end_date:
            rule.active = False  # nothing left to record
        self.repo.add(rule)
        self.repo.db.commit()
        self.repo.db.refresh(rule)
        return self._to_read(rule)

    def set_active(self, rid: UUID, active: bool, today: date | None = None) -> RecurringRead | None:
        rule = self.repo.read(rid)
        if rule is None:
            return None
        today = today or date.today()
        if active and not rule.active:
            # Occurrences that fell due while it was paused are skipped, not recorded late.
            rule.next_date = max(
                rule.next_date, schedule.first_on_or_after(rule.start_date, rule.frequency, rule.every, today)
            )
            rule.last_error = None
            if rule.end_date is not None and rule.next_date > rule.end_date:
                raise ValueError("this recurring transaction has already ended: change its end date to resume it!")
        rule.active = active
        self.repo.add(rule)
        self.repo.db.commit()
        self.repo.db.refresh(rule)
        return self._to_read(rule)

    def delete(self, rid: UUID) -> bool:
        rule = self.repo.read(rid)
        if rule is None:
            return False
        self.repo.delete(rule)
        self.repo.db.commit()
        return True

    def process_due(self, today: date | None = None) -> int:
        """Record every occurrence that has fallen due; returns how many were recorded. Safe to call
        often and from several workers at once: an occurrence is only ever recorded once."""
        today = today or date.today()
        recorded = 0
        for rule in self.repo.due(today):
            recorded += self._catch_up(rule, today)
        return recorded

    def _catch_up(self, rule: RecurringTransaction, today: date) -> int:
        recorded = 0
        while rule.active and rule.next_date <= today and recorded < MAX_PER_RUN:
            if rule.end_date is not None and rule.next_date > rule.end_date:
                break
            day = rule.next_date
            try:
                if not self.repo.recorded(rule.rid, day):
                    self.transactions.create(self._transaction(self._to_read(rule), day), recurring=(rule.rid, day))
                    recorded += 1
            except IntegrityError:
                self.repo.db.rollback()  # another worker recorded it a moment ago
                rule = self.repo.read(rule.rid)
            except (ValueError, ValidationError) as e:
                self.repo.db.rollback()
                rule = self.repo.read(rule.rid)
                message = validation_message(e) if isinstance(e, ValidationError) else str(e)
                rule.last_error = f"{day.isoformat()}: {message}"[:300]
                self.repo.add(rule)
                self.repo.db.commit()
                return recorded
            rule.last_date = day
            rule.next_date = schedule.first_after(rule.start_date, rule.frequency, rule.every, day)
            rule.last_error = None
        if rule.end_date is not None and rule.next_date > rule.end_date:
            rule.active = False
        rule.updated = utc_now()
        self.repo.add(rule)
        self.repo.db.commit()
        return recorded
