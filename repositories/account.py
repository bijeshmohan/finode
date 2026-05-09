from uuid import UUID

from sqlmodel import Session, select

from models.account import Account
from schemas.account import AccountCreate, AccountUpdate


def create(db: Session, data: AccountCreate) -> Account:
    account = Account(
        name=data.name,
        balance=data.balance,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def read(db: Session, aid: UUID) -> Account | None:
    statement = select(Account).where(Account.aid == aid)
    account = db.exec(statement).first()
    return account


def read_all(db: Session) -> list[Account]:
    statement = select(Account)
    accounts = db.exec(statement).all()
    return accounts


def update(db: Session, aid: UUID, data: AccountUpdate) -> Account | None:
    account = db.get(Account, aid)
    if not account:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def delete(db: Session, aid: UUID) -> Account | None:
    account = db.get(Account, aid)
    if not account:
        return None
    db.delete(account)
    db.commit()
    return account
