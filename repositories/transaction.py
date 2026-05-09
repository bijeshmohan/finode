from uuid import UUID

from sqlmodel import Session, select

from models.transaction import Transaction
from schemas.transaction import (ExpenseCreate, ExpenseUpdate, IncomeCreate,
                                 IncomeUpdate, TransferCreate, TransferUpdate)


def create(
    db: Session,
    data: ExpenseCreate | IncomeCreate | TransferCreate
) -> Transaction:
    transaction = Transaction(**data.model_dump())
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def read(db: Session, tid: UUID) -> Transaction | None:
    statement = select(Transaction).where(Transaction.tid == tid)
    transaction = db.exec(statement).first()
    return transaction


def read_all(db: Session) -> list[Transaction]:
    statement = select(Transaction)
    transactions = db.exec(statement).all()
    return transactions


def update(
    db: Session,
    tid: UUID,
    data: ExpenseUpdate | IncomeUpdate | TransferUpdate
) -> Transaction | None:
    transaction = db.get(Transaction, tid)
    if not transaction:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(transaction, key, value)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def delete(db: Session, tid: UUID) -> Transaction | None:
    transaction = db.get(Transaction, tid)
    if not transaction:
        return None
    db.delete(transaction)
    db.commit()
    return transaction
