from uuid import UUID

from sqlmodel import Session, select

from ..models.account import Account
from ..schemas.account import AccountCreate, AccountUpdate


class AccountRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def create(self, data: AccountCreate, commodity_id: UUID | None = None) -> Account:
        values = data.model_dump(exclude={"balance", "balance_value", "commodity"})
        account = Account(**values, commodity_id=commodity_id, user=self.uid)
        self.db.add(account)
        self.db.flush()
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
        parent_id: UUID | None = None,
    ) -> Account | None:
        statement = select(Account).where(
            Account.name == name,
            Account.user == self.uid,
            Account.parent_id == parent_id,
        )
        account = self.db.exec(statement).first()
        return account

    def update(self, aid: UUID, data: AccountUpdate, commodity_id: UUID | None = None) -> Account | None:
        account = self.read(aid)
        if not account:
            return None
        values = data.model_dump(exclude_unset=True, exclude={"balance", "balance_value", "commodity"})
        for key, value in values.items():
            setattr(account, key, value)
        if commodity_id is not None:
            account.commodity_id = commodity_id
        self.db.add(account)
        self.db.flush()
        return account

    def delete(self, aid: UUID) -> Account | None:
        account = self.read(aid)
        if not account:
            return None
        self.db.delete(account)
        self.db.flush()
        return account

    def has_children(self, aid: UUID) -> bool:
        statement = select(Account).where(
            Account.parent_id == aid,
            Account.user == self.uid,
        )
        return self.db.exec(statement).first() is not None

