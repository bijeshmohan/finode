"""Persistence for budget categories, always filtered by the user's id.

Until the pages move over to categories, every Income or Expenses account has a category of the same id (its "own"
account): `AccountRepository` keeps the pair in step, and the helpers here do the category's side of that."""

import builtins
from uuid import UUID

from sqlmodel import Session, col, select

from ..models.account import Account
from ..models.category import BudgetCategory
from .cache import remembered

# The root accounts a category's books account hangs under, and the kind each stands for.
ROOT_KINDS = {"Expenses": "spending", "Income": "earning"}


class CategoryRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self) -> builtins.list[BudgetCategory]:
        """Every category of the person, loaded once per session (see repositories/cache.py)."""
        statement = select(BudgetCategory).where(BudgetCategory.user == self.uid)
        return list(remembered(self.db, ("categories", self.uid), lambda: self.db.exec(statement).all()))

    def read(self, bcid: UUID) -> BudgetCategory | None:
        return next((c for c in self.list() if c.bcid == bcid), None)

    def by_system_key(self, key: str) -> BudgetCategory | None:
        return next((c for c in self.list() if c.system_key == key), None)

    def has_children(self, bcid: UUID) -> bool:
        return any(c.parent_id == bcid for c in self.list())

    def accounts_of(self, bcid: UUID) -> builtins.list[Account]:
        """The books accounts that stand for a category (its own, and any others the person attached)."""
        return builtins.list(
            self.db.exec(select(Account).where(Account.user == self.uid, Account.category_id == bcid)).all()
        )

    def used_by_lines(self, bcid: UUID) -> bool:
        from ..models.transaction import Posting

        return (
            self.db.exec(
                select(Posting.pid).where(Posting.user == self.uid, Posting.category_id == bcid).limit(1)
            ).first()
            is not None
        )

    # ---- keeping an account's own category in step ------------------------------------------------

    @staticmethod
    def kind_of(account: Account, by_id: dict[UUID, Account]) -> str | None:
        """'spending' or 'earning' for an Income or Expenses account below the roots, else None."""
        seen: set[UUID] = set()
        current = account
        while current.parent_id is not None and current.parent_id in by_id and current.aid not in seen:
            seen.add(current.aid)
            current = by_id[current.parent_id]
        if current.parent_id is not None or account.parent_id is None:
            return None
        return ROOT_KINDS.get(current.name)

    def mirror_create(self, account: Account, by_id: dict[UUID, Account]) -> None:
        """Give an Income or Expenses account its own category (the same id), under its parent's. Others are left alone."""
        kind = self.kind_of(account, by_id)
        if kind is None or account.category_id is not None:
            return
        parent = by_id.get(account.parent_id) if account.parent_id else None
        self.db.add(
            BudgetCategory(
                bcid=account.aid,
                user=self.uid,
                name=account.name,
                details=account.details,
                kind=kind,
                parent_id=parent.category_id if parent is not None and parent.parent_id is not None else None,
                closed_on=account.closed_on,
            )
        )
        self.db.flush()
        account.category_id = account.aid
        self.db.add(account)
        self.db.flush()

    def mirror_update(self, account: Account, by_id: dict[UUID, Account]) -> None:
        """Copy an account's name, note, place and closing day to its own category."""
        if account.category_id != account.aid:
            return
        category = self.db.get(BudgetCategory, account.aid)
        if category is None:
            return
        parent = by_id.get(account.parent_id) if account.parent_id else None
        category.name, category.details, category.closed_on = account.name, account.details, account.closed_on
        category.parent_id = parent.category_id if parent is not None and parent.parent_id is not None else None
        self.db.add(category)
        self.db.flush()

    def mirror_delete(self, aid: UUID) -> None:
        category = self.db.get(BudgetCategory, aid)
        if category is not None and category.user == self.uid:
            self.db.delete(category)
            self.db.flush()

    def set_system_key(self, bcid: UUID, key: str) -> None:
        category = self.db.get(BudgetCategory, bcid)
        if category is not None:
            category.system_key = key
            self.db.add(category)
            self.db.flush()

    def children_of(self, bcid: UUID) -> builtins.list[BudgetCategory]:
        return builtins.list(
            self.db.exec(
                select(BudgetCategory).where(BudgetCategory.user == self.uid, col(BudgetCategory.parent_id) == bcid)
            ).all()
        )
