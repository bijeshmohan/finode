from uuid import UUID

from sqlmodel import Session, select

from ..models.account import Account, AccountType
from ..schemas.account import AccountCreate, AccountUpdate


class AccountRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def create(self, data: AccountCreate) -> Account:
        values = data.model_dump(exclude={"balance"})
        account = Account(**values, user=self.uid)
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account

    def read(self, aid: UUID) -> Account | None:
        statement = select(Account).where(
            Account.aid == aid,
            Account.user == self.uid,
        )
        account = self.db.exec(statement).first()
        return account

    def list(self) -> list[Account]:
        statement = select(Account).where(Account.user == self.uid)
        accounts = self.db.exec(statement).all()
        return accounts

    def read_by_name(
        self,
        name: str,
        account_type: AccountType | None = None,
    ) -> Account | None:
        statement = select(Account).where(
            Account.name == name,
            Account.user == self.uid,
        )
        if account_type is not None:
            statement = statement.where(Account.type == account_type)
        account = self.db.exec(statement).first()
        return account

    def update(self, aid: UUID, data: AccountUpdate) -> Account | None:
        account = self.read(aid)
        if not account:
            return None
        values = data.model_dump(exclude_unset=True, exclude={"balance"})
        for key, value in values.items():
            setattr(account, key, value)
        self.db.add(account)
        self.db.commit()
        self.db.refresh(account)
        return account

    def delete(self, aid: UUID) -> Account | None:
        account = self.read(aid)
        if not account:
            return None
        self.db.delete(account)
        self.db.commit()
        return account
