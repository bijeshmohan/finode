from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, select

from .commodity import CommodityRepository
from ..models.account import Account
from ..models.transaction import Transaction, Posting
from ..models.transaction_history import TransactionHistory
from ..schemas.transaction import TransactionCreate, TransactionUpdate


class TransactionRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def create(
        self,
        data: TransactionCreate,
        currency_id: UUID | None = None,
        values: list[Decimal] | None = None,
        origin: str | None = None,
        recurring: tuple[UUID, date] | None = None,
    ) -> Transaction:
        """`values` are the postings' worth in the currency, in order; a posting without one is worth its amount."""
        fields = data.model_dump(exclude={"postings", "currency"})
        if currency_id is None:
            currency_id = CommodityRepository(self.db, self.uid).default_currency().cid
        transaction = Transaction(
            **fields, currency_id=currency_id, user=self.uid, created_via=origin, updated_via=origin
        )
        if recurring is not None:
            transaction.recurring_id, transaction.recurring_date = recurring
        self.db.add(transaction)
        self.db.flush()
        self._add_postings(transaction, data.postings, values)
        self.db.flush()
        self._record(transaction, "created", origin)
        return transaction

    def _record(self, transaction: Transaction, action: str, origin: str | None) -> None:
        """Append what the transaction looks like now to its history."""
        snapshot = {
            "date": transaction.date.isoformat(),
            "payee": transaction.payee,
            "comment": transaction.comment,
            "currency_id": str(transaction.currency_id),
            "recurring_id": str(transaction.recurring_id) if transaction.recurring_id else None,
            "postings": [
                {"account": str(p.account), "side": p.side.value, "amount": str(p.amount), "value": str(p.value)}
                for p in sorted(self.postings(transaction.tid), key=lambda p: (p.created, str(p.pid)))
            ],
        }
        if action == "updated":
            previous = self.history(transaction.tid)
            if previous and previous[-1].snapshot == snapshot:
                return  # saved without changing anything
        self.db.add(
            TransactionHistory(
                user=self.uid, transaction_id=transaction.tid, action=action, via=origin, snapshot=snapshot
            )
        )
        self.db.flush()

    def history(self, tid: UUID) -> list[TransactionHistory]:
        statement = (
            select(TransactionHistory)
            .where(TransactionHistory.transaction_id == tid, TransactionHistory.user == self.uid)
            .order_by(TransactionHistory.at, TransactionHistory.hid)
        )
        return self.db.exec(statement).all()

    def deleted(self) -> list[TransactionHistory]:
        """The deletion record of every transaction that no longer exists, newest first."""
        statement = (
            select(TransactionHistory)
            .where(TransactionHistory.user == self.uid, TransactionHistory.action == "deleted")
            .order_by(TransactionHistory.at.desc())
        )
        return self.db.exec(statement).all()

    def _add_postings(self, transaction: Transaction, postings, values: list[Decimal] | None) -> None:
        for index, posting_data in enumerate(postings):
            worth = values[index] if values is not None else (posting_data.value or posting_data.amount)
            self.db.add(
                Posting(
                    **posting_data.model_dump(exclude={"value"}),
                    value=worth,
                    transaction=transaction.tid,
                    user=self.uid,
                )
            )

    def read(self, tid: UUID) -> Transaction | None:
        statement = select(Transaction).where(
            Transaction.tid == tid,
            Transaction.user == self.uid,
        )
        transaction = self.db.exec(statement).first()
        return transaction

    def list(
        self,
        account_ids: list[UUID] | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Transaction]:
        statement = select(Transaction).where(Transaction.user == self.uid)
        if account_ids is not None:
            statement = statement.where(
                Transaction.tid.in_(
                    select(Posting.transaction).where(
                        Posting.account.in_(account_ids),
                        Posting.user == self.uid,
                    )
                )
            )
        if date_from is not None:
            statement = statement.where(Transaction.date >= date_from)
        if date_to is not None:
            statement = statement.where(Transaction.date <= date_to)
        statement = statement.order_by(
            Transaction.date.desc(),
            Transaction.created.desc(),
        ).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        transactions = self.db.exec(statement).all()
        return transactions

    def postings(self, tid: UUID) -> list[Posting]:
        statement = select(Posting).where(
            Posting.transaction == tid,
            Posting.user == self.uid,
        )
        postings = self.db.exec(statement).all()
        return postings

    def all_postings(self) -> list[Posting]:
        return self.db.exec(select(Posting).where(Posting.user == self.uid)).all()

    def conversions(self) -> list[tuple[UUID, UUID, date, Decimal, Decimal, datetime]]:
        """Postings made in a different commodity than their transaction's currency.

        Each is (commodity, currency, date, amount, value, created): `value / amount` is
        the rate the user actually got.
        """
        statement = (
            select(
                Account.commodity_id,
                Transaction.currency_id,
                Transaction.date,
                Posting.amount,
                Posting.value,
                Posting.created,
            )
            .join(Transaction, Transaction.tid == Posting.transaction)
            .join(Account, Account.aid == Posting.account)
            .where(Posting.user == self.uid, Account.commodity_id != Transaction.currency_id)
        )
        return [tuple(row) for row in self.db.exec(statement).all()]

    def postings_for_account(self, aid: UUID) -> list[Posting]:
        statement = select(Posting).where(
            Posting.account == aid,
            Posting.user == self.uid,
        )
        postings = self.db.exec(statement).all()
        return postings

    def postings_for_accounts(
        self,
        aids: list[UUID],
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[Posting]:
        if not aids:
            return []
        statement = select(Posting).where(
            Posting.account.in_(aids),
            Posting.user == self.uid,
        )
        if date_from is not None or date_to is not None:
            statement = statement.join(
                Transaction, Transaction.tid == Posting.transaction
            )
            if date_from is not None:
                statement = statement.where(Transaction.date >= date_from)
            if date_to is not None:
                statement = statement.where(Transaction.date <= date_to)
        postings = self.db.exec(statement).all()
        return postings

    def update(
        self,
        tid: UUID,
        data: TransactionUpdate,
        currency_id: UUID | None = None,
        values: list[Decimal] | None = None,
        origin: str | None = None,
    ) -> Transaction | None:
        transaction = self.read(tid)
        if not transaction:
            return None

        fields = data.model_dump(exclude_unset=True, exclude={"postings", "currency"})
        for key, value in fields.items():
            setattr(transaction, key, value)
        if currency_id is not None:
            transaction.currency_id = currency_id
        if origin is not None:
            transaction.updated_via = origin

        if data.postings is not None:
            self._replace_postings(transaction, data.postings, values)

        self.db.add(transaction)
        self.db.flush()
        self._record(transaction, "updated", origin)
        return transaction

    def _replace_postings(self, transaction: Transaction, postings, values: list[Decimal] | None) -> None:
        """Make the transaction's postings the given ones, keeping a posting's id when it lives on.

        A new posting takes over an existing one on the same account and side (then on the same
        account); what is left over is added or removed. So correcting an amount never replaces the posting.
        """
        remaining = list(self.postings(transaction.tid))
        planned = [
            (data, values[index] if values is not None else (data.value or data.amount))
            for index, data in enumerate(postings)
        ]
        taken: list[Posting | None] = [None] * len(planned)
        for exact in (True, False):
            for index, (data, _) in enumerate(planned):
                if taken[index] is not None:
                    continue
                for old in remaining:
                    if old.account == data.account and (not exact or old.side == data.side):
                        taken[index] = old
                        remaining.remove(old)
                        break
        for posting in remaining:
            self.db.delete(posting)
        for (data, worth), old in zip(planned, taken):
            if old is None:
                self.db.add(
                    Posting(
                        **data.model_dump(exclude={"value"}), value=worth, transaction=transaction.tid, user=self.uid
                    )
                )
            else:
                old.account, old.side, old.amount, old.value = data.account, data.side, data.amount, worth
                self.db.add(old)
        self.db.flush()

    def delete(self, tid: UUID, origin: str | None = None) -> Transaction | None:
        transaction = self.read(tid)
        if not transaction:
            return None
        self._record(transaction, "deleted", origin)
        for posting in self.postings(tid):
            self.db.delete(posting)
        self.db.delete(transaction)
        self.db.flush()
        return transaction
