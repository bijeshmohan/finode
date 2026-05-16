from uuid import UUID

from sqlmodel import Session, select

from ..models.account import Account
from ..schemas.account import AccountCreate, AccountUpdate


class AccountRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: AccountCreate) -> Account:
        account = Account(**data.model_dump())
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account

    def read(self, aid: UUID) -> Account | None:
        statement = select(Account).where(Account.aid == aid)
        account = self.db.exec(statement).first()
        return account

    def list(self) -> list[Account]:  # TODO: filter by date, type, category etc.
        statement = select(Account)
        accounts = self.db.exec(statement).all()
        return accounts

    def update(self, aid: UUID, data: AccountUpdate) -> Account | None:
        account = self.db.get(Account, aid)
        if not account:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(account, key, value)
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account

    def delete(self, aid: UUID) -> Account | None:
        account = self.db.get(Account, aid)
        if not account:
            return None
        self.db.delete(account)
        self.db.commit()
        return account
