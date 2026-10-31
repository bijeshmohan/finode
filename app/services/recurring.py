"""Recurring transactions: validating a rule, recording every occurrence that is due, skipping one, pausing and resuming."""

import builtins
from datetime import date
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from ..clock import local_today
from ..models.recurring import RecurringTransaction
from ..models.transaction import PostingSide
from ..models.utils import utc_now
from ..repositories.recurring import RecurringRepository
from ..schemas.recurring import RecurringCreate, RecurringPostingData, RecurringRead, RecurringUpdate
from ..schemas.transaction import PostingCreate, TransactionCreate
from . import schedule
from .account import AccountService
from .simple import label_simple, simple_postings
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
        read.category = rule.category_id
        read.postings = [
            RecurringPostingData(account=p.account, side=PostingSide(p.side), amount=p.amount, category=p.category_id)
            for p in rows.get(rule.rid, [])
        ]
        return read

    def list(self) -> builtins.list[RecurringRead]:
        rows = self.repo.postings()
        return [self._to_read(r, rows) for r in self.repo.list()]

    def read(self, rid: UUID) -> RecurringRead | None:
        rule = self.repo.read(rid)
        return self._to_read(rule) if rule else None

    def _transaction(self, rule_like, day: date) -> TransactionCreate:
        if rule_like.postings:
            return TransactionCreate(
                date=day,
                payee=rule_like.payee,
                comment=rule_like.comment,
                tags=list(rule_like.tags),
                postings=[
                    PostingCreate(account=p.account, side=p.side, amount=p.amount, category=p.category)
                    for p in rule_like.postings
                ],
            )
        postings = simple_postings(rule_like.amount, rule_like.from_account, rule_like.to_account)
        if rule_like.category is not None:
            label_simple({a.aid: a for a in self.accounts.ar.list()}, postings, rule_like.category)
        return TransactionCreate(
            date=day, payee=rule_like.payee, comment=rule_like.comment, tags=list(rule_like.tags), postings=postings
        )

    def _rows_on_roots[T: RecurringCreate | RecurringUpdate](self, data: T) -> T:
        """A row that names only its category records on Expenses (a spending category) or Income (an earning one)."""
        if not any(p.account is None for p in data.postings):
            return data
        categories = {c.bcid: c for c in self.transactions.cr.list()}
        roots = {a.name: a.aid for a in self.accounts.ar.list() if a.parent_id is None}
        rows = []
        for p in data.postings:
            if p.account is None:
                category = categories.get(p.category) if p.category else None
                if category is None:
                    raise ValueError(f"category with bcid '{p.category}' not found!")
                p = p.model_copy(update={"account": roots["Expenses" if category.kind == "spending" else "Income"]})
            rows.append(p)
        return data.model_copy(update={"postings": rows})

    @staticmethod
    def _rows(data) -> builtins.list[dict]:
        return [
            {"account": p.account, "side": p.side.value, "amount": p.amount, "category_id": p.category}
            for p in data.postings
        ]

    def _keep_labels[T: RecurringCreate | RecurringUpdate](self, rule: RecurringTransaction, data: T) -> T:
        """A change that does not mention categories (the web form has no field for them yet) keeps the ones the rule
        had, as long as the account they were on is still in the rule. Sending null takes a category off."""
        update: dict = {}
        if "category" not in data.model_fields_set and rule.category_id is not None:
            same = (rule.from_account, rule.to_account) == (data.from_account, data.to_account)
            if same and not data.postings:
                update["category"] = rule.category_id
        if data.postings:
            old = {
                (row.account, row.side): row.category_id
                for row in self.repo.postings().get(rule.rid, [])
                if row.category_id is not None
            }
            rows = [
                p.model_copy(update={"category": old.get((p.target, p.side.value))})
                if "category" not in p.model_fields_set and old.get((p.target, p.side.value))
                else p
                for p in data.postings
            ]
            update["postings"] = rows
        return data.model_copy(update=update) if update else data

    @staticmethod
    def _fields(data) -> dict:
        """A rule's own columns from what the client sent (the category is stored as `category_id`)."""
        fields = data.model_dump(exclude={"postings", "category"})
        fields["category_id"] = data.category
        return fields

    def as_transaction(self, rule: RecurringRead) -> TransactionCreate:
        """The transaction a rule records (on its start date), for showing it."""
        return self._transaction(rule, rule.start_date)

    def _check(self, data: RecurringCreate | RecurringUpdate) -> None:
        """Refuse a rule that could never be recorded (same checks as recording it by hand)."""
        self.transactions.validate(self._transaction(data, data.start_date))

    def create(self, data: RecurringCreate) -> RecurringRead:
        if len(self.repo.list()) >= MAX_RULES:
            raise ValueError(f"you can have at most {MAX_RULES} recurring transactions!")
        data = self._rows_on_roots(data)
        self._check(data)
        rule = RecurringTransaction(**self._fields(data), user_id=self.repo.uid, next_date=data.start_date)
        self.repo.add(rule)
        self.repo.set_postings(rule.rid, self._rows(data))
        self.repo.db.commit()
        self.repo.db.refresh(rule)
        return self._to_read(rule)

    def update(self, rid: UUID, data: RecurringUpdate) -> RecurringRead | None:
        rule = self.repo.read(rid)
        if rule is None:
            return None
        data = self._keep_labels(rule, self._rows_on_roots(data))
        self._check(data)
        for field, value in self._fields(data).items():
            setattr(rule, field, value)
        self.repo.set_postings(rule.rid, self._rows(data))
        # Carry on after the last occurrence that was recorded (or from the start if none was yet).
        # ... and what was skipped stays skipped.
        handled = max((d for d in (rule.last_date, rule.skipped_date) if d), default=None)
        rule.next_date = (
            schedule.first_after(rule.start_date, rule.frequency, rule.every, handled) if handled else rule.start_date
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
        today = today or local_today()
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

    def skip_next(self, rid: UUID) -> RecurringRead | None:
        """Leave the next occurrence out: nothing is recorded for it and the rule carries on with the one after.
        Meant for one-offs (a month without the subscription); it also clears a problem that kept an occurrence from being recorded."""
        rule = self.repo.read(rid)
        if rule is None:
            return None
        if not rule.active:
            raise ValueError("it is paused or has ended: resume it first, then you can skip an occurrence!")
        day = rule.next_date
        rule.skipped_date = day
        rule.next_date = schedule.first_after(rule.start_date, rule.frequency, rule.every, day)
        rule.last_error = None
        if rule.end_date is not None and rule.next_date > rule.end_date:
            rule.active = False  # that was the last one
        rule.updated = utc_now()
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
        today = today or local_today()
        recorded = 0
        for rule in self.repo.due(today):
            recorded += self._catch_up(rule, today)
        return recorded

    def _reread(self, rule: RecurringTransaction) -> RecurringTransaction:
        """The rule as the database has it now (after a rollback); it cannot have gone, only this worker deletes rules."""
        fresh = self.repo.read(rule.rid)
        return fresh if fresh is not None else rule

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
                rule = self._reread(rule)
            except ValueError as e:  # a ValidationError is one too
                self.repo.db.rollback()
                rule = self._reread(rule)
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
