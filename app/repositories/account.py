"""Persistence for accounts, always filtered by the user's id."""

import builtins
from datetime import date
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
        account = Account(**values, on_budget=on_budget, user_id=self.uid)
        self.db.add(account)
        self.db.flush()
        if record:
            self._record(account, "created")
        return account

    def _snapshot(self, account: Account) -> dict:
        by_id = {a.id: a for a in self.list()}
        names: builtins.list[str] = []
        seen: set[UUID] = set()
        current: Account | None = account
        while current is not None and current.id not in seen:
            seen.add(current.id)
            names.append(current.name)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return {
            "name": account.name,
            "path": ":".join(reversed(names)),
            "parent_id": str(account.parent_id) if account.parent_id else None,
            "details": account.details,
            "on_budget": account.on_budget,
            "statement_day": account.statement_day,
            "due_day": account.due_day,
            "closed_on": account.closed_on.isoformat() if account.closed_on else None,
        }

    def _record(self, account: Account, action: str, **extra) -> None:
        """Append what the account looks like now to its history (an unchanged save adds nothing)."""
        snapshot = {**self._snapshot(account), **extra}
        if action == "updated" and not extra:
            previous = self.history(account.id)
            # Steps written before the bill days existed lack the two keys: they read as empty.
            before = {"statement_day": None, "due_day": None, **previous[-1].snapshot} if previous else {}
            if previous and {k: v for k, v in before.items() if not k.startswith("merged_")} == snapshot:
                return
        self.db.add(
            AccountHistory(user_id=self.uid, account_id=account.id, action=action, via=self.origin, snapshot=snapshot)
        )
        self.db.flush()

    def history(self, account_id: UUID) -> builtins.list[AccountHistory]:
        """What happened to one account, oldest first (works for a deleted one too)."""
        return self.db.exec(
            select(AccountHistory)
            .where(AccountHistory.user_id == self.uid, AccountHistory.account_id == account_id)
            .order_by(AccountHistory.at, AccountHistory.id)
        ).all()

    def history_since(self, since, via: str | None, limit: int) -> builtins.list[AccountHistory]:
        """The newest history rows of every account, optionally from a moment on and by one origin ("assistant" is any)."""
        statement = select(AccountHistory).where(AccountHistory.user_id == self.uid)
        if since is not None:
            statement = statement.where(AccountHistory.at >= since)
        if via == "assistant":
            statement = statement.where(col(AccountHistory.via).startswith("mcp:"))
        elif via:
            statement = statement.where(AccountHistory.via == via)
        return self.db.exec(
            statement.order_by(col(AccountHistory.at).desc(), col(AccountHistory.id)).limit(limit)
        ).all()

    def histories_for(self, aids: builtins.list[UUID]) -> builtins.list[AccountHistory]:
        if not aids:
            return []
        return self.db.exec(
            select(AccountHistory)
            .where(AccountHistory.user_id == self.uid, col(AccountHistory.account_id).in_(aids))
            .order_by(AccountHistory.at, AccountHistory.id)
        ).all()

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
        self._record(account, "updated")
        return account

    def delete(self, account_id: UUID, **extra) -> Account | None:
        account = self.read(account_id)
        if not account:
            return None
        self._record(account, "deleted", **extra)
        self.db.delete(account)
        self.db.flush()
        return account

    def record_deletion(self, account_id: UUID, snapshot: dict) -> None:
        self.db.add(AccountDeletion(user_id=self.uid, account_id=account_id, snapshot=snapshot))
        self.db.flush()

    def deletions(self) -> builtins.list[AccountDeletion]:
        """Every deletion, newest first."""
        return self.db.exec(
            select(AccountDeletion).where(AccountDeletion.user_id == self.uid).order_by(col(AccountDeletion.at).desc())
        ).all()

    def deletion(self, deletion_id: UUID) -> AccountDeletion | None:
        return self.db.exec(
            select(AccountDeletion).where(AccountDeletion.id == deletion_id, AccountDeletion.user_id == self.uid)
        ).first()

    def restore(self, account_id: UUID, fields: dict) -> Account:
        """Put a deleted account back with its old id."""
        account = Account(id=account_id, user_id=self.uid, **fields)
        self.db.add(account)
        self.db.flush()
        self._record(account, "restored")
        return account

    def set_closed(self, aids: builtins.list[UUID], day: date | None) -> None:
        for account in self.db.exec(
            select(Account).where(Account.user_id == self.uid, col(Account.id).in_(aids))
        ).all():
            account.closed_on = day
            self.db.add(account)
            self.db.flush()
            self._record(account, "closed" if day else "reopened")
        self.db.flush()

    def has_children(self, account_id: UUID) -> bool:
        statement = select(Account).where(
            Account.parent_id == account_id,
            Account.user_id == self.uid,
        )
        return self.db.exec(statement).first() is not None
