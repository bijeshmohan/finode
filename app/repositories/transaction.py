from datetime import date
from uuid import UUID

from sqlmodel import Session, select

from ..models.transaction import Transaction, Posting
from ..schemas.transaction import TransactionCreate, TransactionUpdate


class TransactionRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def create(self, data: TransactionCreate) -> Transaction:
        values = data.model_dump(exclude={"postings"})
        transaction = Transaction(**values, user=self.uid)
        self.db.add(transaction)
        self.db.flush()
        for posting_data in data.postings:
            posting = Posting(
                **posting_data.model_dump(),
                transaction=transaction.tid,
                user=self.uid,
            )
            self.db.add(posting)
        self.db.flush()
        return transaction

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

    def update(self, tid: UUID, data: TransactionUpdate) -> Transaction | None:
        transaction = self.read(tid)
        if not transaction:
            return None

        values = data.model_dump(exclude_unset=True, exclude={"postings"})
        for key, value in values.items():
            setattr(transaction, key, value)

        if data.postings is not None:
            for posting in self.postings(tid):
                self.db.delete(posting)
            self.db.flush()
            for posting_data in data.postings:
                posting = Posting(
                    **posting_data.model_dump(),
                    transaction=transaction.tid,
                    user=self.uid,
                )
                self.db.add(posting)

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
