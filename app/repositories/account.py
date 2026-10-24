"""Persistence for accounts, always filtered by the user's id."""

from datetime import date
from uuid import UUID

from sqlmodel import Session, func, select

from ..models.account import Account
from ..models.account_deletion import AccountDeletion
from ..schemas.account import AccountCreate, AccountUpdate
from .cache import remembered


class AccountRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def create(self, data: AccountCreate, on_budget: bool = False) -> Account:
        values = data.model_dump(exclude={"balance", "on_budget"})
        account = Account(**values, on_budget=on_budget, user=self.uid)
        self.db.add(account)
        self.db.flush()
        return account

    def count(self) -> int:
        return self.db.exec(select(func.count()).select_from(Account).where(Account.user == self.uid)).one()

    def read(self, aid: UUID) -> Account | None:
        statement = select(Account).where(
            Account.aid == aid,
            Account.user == self.uid,
        )
        account = self.db.exec(statement).first()
        return account

    def list(self) -> list[Account]:
        """Every account of the person, loaded once per session (see repositories/cache.py)."""
        statement = select(Account).where(Account.user == self.uid)
        return list(remembered(self.db, ("accounts", self.uid), lambda: self.db.exec(statement).all()))

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

    def update(
        self,
        aid: UUID,
        data: AccountUpdate,
        on_budget: bool | None = None,
        payment_category: UUID | type(...) | None = ...,
    ) -> Account | None:
        account = self.read(aid)
        if not account:
            return None
        values = data.model_dump(exclude_unset=True, exclude={"balance", "on_budget", "payment_category_id"})
        for key, value in values.items():
            setattr(account, key, value)
        if on_budget is not None:
            account.on_budget = on_budget
        if payment_category is not ...:
            account.payment_category_id = payment_category
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

    def record_deletion(self, account_id: UUID, snapshot: dict) -> None:
        self.db.add(AccountDeletion(user=self.uid, account_id=account_id, snapshot=snapshot))
        self.db.flush()

    def deletions(self) -> list[AccountDeletion]:
        """Every deletion, newest first."""
        return self.db.exec(
            select(AccountDeletion).where(AccountDeletion.user == self.uid).order_by(AccountDeletion.at.desc())
        ).all()

    def deletion(self, did: UUID) -> AccountDeletion | None:
        return self.db.exec(
            select(AccountDeletion).where(AccountDeletion.did == did, AccountDeletion.user == self.uid)
        ).first()

    def restore(self, aid: UUID, fields: dict) -> Account:
        """Put a deleted account back with its old id."""
        account = Account(aid=aid, user=self.uid, **fields)
        self.db.add(account)
        self.db.flush()
        return account

    def set_closed(self, aids: list[UUID], day: date | None) -> None:
        for account in self.db.exec(select(Account).where(Account.user == self.uid, Account.aid.in_(aids))).all():
            account.closed_on = day
            self.db.add(account)
        self.db.flush()

    def clear_payment_category(self, category_id: UUID) -> None:
        """Accounts whose payments were budgeted under this category (it is being deleted) stop pointing at it."""
        for account in self.db.exec(
            select(Account).where(Account.user == self.uid, Account.payment_category_id == category_id)
        ).all():
            account.payment_category_id = None
            self.db.add(account)
        self.db.flush()

    def has_children(self, aid: UUID) -> bool:
        statement = select(Account).where(
            Account.parent_id == aid,
            Account.user == self.uid,
        )
        return self.db.exec(statement).first() is not None
