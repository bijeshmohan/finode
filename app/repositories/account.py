"""Persistence for accounts, always filtered by the user's id."""

import builtins
from datetime import date
from types import EllipsisType
from uuid import UUID

from sqlmodel import Session, col, func, select

from ..models.account import Account
from ..models.account_deletion import AccountDeletion
from ..models.account_history import AccountHistory
from ..schemas.account import AccountCreate, AccountUpdate
from .cache import remembered


class AccountRepository:
    def __init__(self, db: Session, uid: UUID, origin: str | None = None):
        self.db = db
        self.uid = uid
        # Who is making the changes ("web", "api", "mcp:<token name>"), written into the account's history.
        self.origin = origin

    def create(self, data: AccountCreate, on_budget: bool = False, record: bool = True) -> Account:
        """`record=False` is for what finode makes by itself (the Opening Balances account): no history row."""
        values = data.model_dump(exclude={"balance", "on_budget"})
        account = Account(**values, on_budget=on_budget, user=self.uid)
        self.db.add(account)
        self.db.flush()
        if record:
            self._record(account, "created")
        return account

    def _snapshot(self, account: Account) -> dict:
        by_id = {a.aid: a for a in self.list()}
        names: builtins.list[str] = []
        seen: set[UUID] = set()
        current: Account | None = account
        while current is not None and current.aid not in seen:
            seen.add(current.aid)
            names.append(current.name)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return {
            "name": account.name,
            "path": ":".join(reversed(names)),
            "parent_id": str(account.parent_id) if account.parent_id else None,
            "details": account.details,
            "on_budget": account.on_budget,
            "payment_category_id": str(account.payment_category_id) if account.payment_category_id else None,
            "closed_on": account.closed_on.isoformat() if account.closed_on else None,
        }

    def _record(self, account: Account, action: str, **extra) -> None:
        """Append what the account looks like now to its history (an unchanged save adds nothing)."""
        snapshot = {**self._snapshot(account), **extra}
        if action == "updated":
            previous = self.history(account.aid)
            if previous and previous[-1].snapshot == snapshot:
                return
        self.db.add(
            AccountHistory(user=self.uid, account_id=account.aid, action=action, via=self.origin, snapshot=snapshot)
        )
        self.db.flush()

    def history(self, aid: UUID) -> builtins.list[AccountHistory]:
        """What happened to one account, oldest first (works for a deleted one too)."""
        return self.db.exec(
            select(AccountHistory)
            .where(AccountHistory.user == self.uid, AccountHistory.account_id == aid)
            .order_by(AccountHistory.at, AccountHistory.hid)
        ).all()

    def history_since(self, since, via: str | None, limit: int) -> builtins.list[AccountHistory]:
        """The newest history rows of every account, optionally from a moment on and by one origin ("assistant" is any)."""
        statement = select(AccountHistory).where(AccountHistory.user == self.uid)
        if since is not None:
            statement = statement.where(AccountHistory.at >= since)
        if via == "assistant":
            statement = statement.where(col(AccountHistory.via).startswith("mcp:"))
        elif via:
            statement = statement.where(AccountHistory.via == via)
        return self.db.exec(
            statement.order_by(col(AccountHistory.at).desc(), col(AccountHistory.hid)).limit(limit)
        ).all()

    def histories_for(self, aids: builtins.list[UUID]) -> builtins.list[AccountHistory]:
        if not aids:
            return []
        return self.db.exec(
            select(AccountHistory)
            .where(AccountHistory.user == self.uid, col(AccountHistory.account_id).in_(aids))
            .order_by(AccountHistory.at, AccountHistory.hid)
        ).all()

    def count(self) -> int:
        return self.db.exec(select(func.count()).select_from(Account).where(Account.user == self.uid)).one()

    def read(self, aid: UUID) -> Account | None:
        statement = select(Account).where(
            Account.aid == aid,
            Account.user == self.uid,
        )
        account = self.db.exec(statement).first()
        return account

    def list(self) -> builtins.list[Account]:
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
        payment_category: UUID | EllipsisType | None = ...,
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
        self._record(account, "updated")
        return account

    def delete(self, aid: UUID, **extra) -> Account | None:
        account = self.read(aid)
        if not account:
            return None
        self._record(account, "deleted", **extra)
        self.db.delete(account)
        self.db.flush()
        return account

    def record_deletion(self, account_id: UUID, snapshot: dict) -> None:
        self.db.add(AccountDeletion(user=self.uid, account_id=account_id, snapshot=snapshot))
        self.db.flush()

    def deletions(self) -> builtins.list[AccountDeletion]:
        """Every deletion, newest first."""
        return self.db.exec(
            select(AccountDeletion).where(AccountDeletion.user == self.uid).order_by(col(AccountDeletion.at).desc())
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
        self._record(account, "restored")
        return account

    def set_closed(self, aids: builtins.list[UUID], day: date | None) -> None:
        for account in self.db.exec(select(Account).where(Account.user == self.uid, col(Account.aid).in_(aids))).all():
            account.closed_on = day
            self.db.add(account)
            self.db.flush()
            self._record(account, "closed" if day else "reopened")
        self.db.flush()

    def clear_payment_category(self, category_id: UUID) -> None:
        """Accounts whose payments were budgeted under this category (it is being deleted) stop pointing at it."""
        for account in self.db.exec(
            select(Account).where(Account.user == self.uid, Account.payment_category_id == category_id)
        ).all():
            account.payment_category_id = None
            self.db.add(account)
            self.db.flush()
            self._record(account, "updated")
        self.db.flush()

    def has_children(self, aid: UUID) -> bool:
        statement = select(Account).where(
            Account.parent_id == aid,
            Account.user == self.uid,
        )
        return self.db.exec(statement).first() is not None
