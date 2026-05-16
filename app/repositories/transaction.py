from uuid import UUID

from sqlmodel import Session, select

from ..models.transaction import Transaction
from ..schemas.transaction import TransactionCreate, TransactionUpdate


class TransactionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: TransactionCreate) -> Transaction:
        transaction = Transaction(**data.model_dump())
        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(transaction)
        return transaction

    def read(self, tid: UUID) -> Transaction | None:
        statement = select(Transaction).where(Transaction.tid == tid)
        transaction = self.db.exec(statement).first()
        return transaction

    def list(self) -> list[Transaction]:
        statement = select(Transaction)
        transactions = self.db.exec(statement).all()
        return transactions

    def update(self, tid: UUID, data: TransactionUpdate) -> Transaction | None:
        transaction = self.db.get(Transaction, tid)
        if not transaction:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(transaction, key, value)
        self.db.add(transaction)
        self.db.commit()
        self.db.refresh(transaction)
        return transaction

    def delete(self, tid: UUID) -> Transaction | None:
        transaction = self.db.get(Transaction, tid)
        if not transaction:
            return None
        self.db.delete(transaction)
        self.db.commit()
        return transaction
