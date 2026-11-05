"""Persistence for accounts, always filtered by the user's id."""

import builtins
from datetime import date
from uuid import UUID

from sqlmodel import Session, col, func, select

from ..models.account import Account
from ..schemas.account import AccountCreate, AccountUpdate
from .cache import remembered


class AccountRepository:
    def __init__(self, db: Session, uid: UUID, origin: str | None = None):
        self.db = db
        self.uid = uid
        # Who is making the changes ("web", "api", "mcp:<token name>"): the origin a merge writes on the entries it moves.
        self.origin = origin

    def create(self, data: AccountCreate, on_budget: bool = False) -> Account:
        values = data.model_dump(exclude={"balance", "on_budget"})
        account = Account(**values, on_budget=on_budget, user_id=self.uid)
        self.db.add(account)
        self.db.flush()
        return account

    def count(self) -> int:
        return self.db.exec(select(func.count()).select_from(Account).where(Account.user_id == self.uid)).one()

    def read(self, account_id: UUID) -> Account | None:
        statement = select(Account).where(
            Account.id == account_id,
            Account.user_id == self.uid,
        )
        account = self.db.exec(statement).first()
        return account

    def list(self) -> builtins.list[Account]:
        """Every account of the person, loaded once per session (see repositories/cache.py)."""
        statement = select(Account).where(Account.user_id == self.uid)
        return list(remembered(self.db, ("accounts", self.uid), lambda: self.db.exec(statement).all()))

    def read_by_name(
        self,
        name: str,
        parent_id: UUID | None = None,
    ) -> Account | None:
        statement = select(Account).where(
            Account.name == name,
            Account.user_id == self.uid,
            Account.parent_id == parent_id,
        )
        account = self.db.exec(statement).first()
        return account

    def update(
        self,
        account_id: UUID,
        data: AccountUpdate,
        on_budget: bool | None = None,
    ) -> Account | None:
        account = self.read(account_id)
        if not account:
            return None
        values = data.model_dump(exclude_unset=True, exclude={"balance", "on_budget"})
        for key, value in values.items():
            setattr(account, key, value)
        if on_budget is not None:
            account.on_budget = on_budget
        self.db.add(account)
        self.db.flush()
        return account

    def delete(self, account_id: UUID) -> Account | None:
        account = self.read(account_id)
        if not account:
            return None
        self.db.delete(account)
        self.db.flush()
        return account

    def set_closed(self, aids: builtins.list[UUID], day: date | None) -> None:
        for account in self.db.exec(
            select(Account).where(Account.user_id == self.uid, col(Account.id).in_(aids))
        ).all():
            account.closed_on = day
            self.db.add(account)
            self.db.flush()
        self.db.flush()

    def has_children(self, account_id: UUID) -> bool:
        statement = select(Account).where(
            Account.parent_id == account_id,
            Account.user_id == self.uid,
        )
        return self.db.exec(statement).first() is not None
