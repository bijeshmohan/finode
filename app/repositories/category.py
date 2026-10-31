"""Persistence for budget categories, always filtered by the user's id.

A category stands alone: a label on the lines of an entry, apart from the books' accounts (an expense is posted to the
root Expenses account and the line says what it was for)."""

import builtins
from datetime import date
from uuid import UUID

from sqlmodel import Session, col, select

from ..models.category import BudgetCategory
from .cache import remembered

# The root account each kind of category goes on, and the kind each root stands for.
ROOT_KINDS = {"Expenses": "spending", "Income": "earning"}
UNCATEGORISED = "Uncategorised"


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

    def used_by_lines(self, bcid: UUID) -> bool:
        from ..models.transaction import Posting

        return (
            self.db.exec(
                select(Posting.pid).where(Posting.user == self.uid, Posting.category_id == bcid).limit(1)
            ).first()
            is not None
        )

    def add(self, category: BudgetCategory) -> BudgetCategory:
        self.db.add(category)
        self.db.flush()
        return category

    def save(self, category: BudgetCategory) -> BudgetCategory:
        self.db.add(category)
        self.db.flush()
        return category

    def delete(self, category: BudgetCategory) -> None:
        self.db.delete(category)
        self.db.flush()

    def set_closed(self, bcids: builtins.list[UUID], day: date | None) -> None:
        for category in self.list():
            if category.bcid in bcids:
                category.closed_on = day
                self.db.add(category)
        self.db.flush()

    def ensure_uncategorised(self, kind: str) -> BudgetCategory:
        """The built-in Uncategorised of a kind, made the first time it is needed and reopened if it was closed."""
        key = f"uncategorised.{kind}"
        found = self.by_system_key(key)
        if found is not None:
            if found.closed_on is not None:
                found.closed_on = None
                self.save(found)
            return found
        taken = {c.name.casefold() for c in self.list() if c.parent_id is None and c.kind == kind}
        name = UNCATEGORISED if UNCATEGORISED.casefold() not in taken else f"{UNCATEGORISED} (built-in)"
        return self.add(BudgetCategory(user=self.uid, name=name, kind=kind, system_key=key))

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
