from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, select

from .commodity import CommodityRepository
from ..models.account import Account
from ..models.transaction import Transaction, Posting
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
    ) -> Transaction:
        """`values` are the postings' worth in the currency, in order; a posting without one is worth its amount."""
        fields = data.model_dump(exclude={"postings", "currency"})
        if currency_id is None:
            currency_id = CommodityRepository(self.db, self.uid).default_currency().cid
        transaction = Transaction(**fields, currency_id=currency_id, user=self.uid)
        self.db.add(transaction)
        self.db.flush()
        self._add_postings(transaction, data.postings, values)
        self.db.flush()
        return transaction

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
    ) -> Transaction | None:
        transaction = self.read(tid)
        if not transaction:
            return None

        fields = data.model_dump(exclude_unset=True, exclude={"postings", "currency"})
        for key, value in fields.items():
            setattr(transaction, key, value)
        if currency_id is not None:
            transaction.currency_id = currency_id

        if data.postings is not None:
            for posting in self.postings(tid):
                self.db.delete(posting)
            self.db.flush()
            self._add_postings(transaction, data.postings, values)

        self.db.add(transaction)
        self.db.flush()
        return transaction

    def delete(self, tid: UUID) -> Transaction | None:
        transaction = self.read(tid)
        if not transaction:
            return None
        for posting in self.postings(tid):
            self.db.delete(posting)
        self.db.delete(transaction)
        self.db.flush()
        return transaction
