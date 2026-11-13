"""Persistence for the budget plan, always filtered by the user's id."""

import builtins
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, select

from ..models.budget import BudgetAllocation
from .cache import remembered


class BudgetRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self, up_to: date | None = None) -> builtins.list[BudgetAllocation]:
        statement = select(BudgetAllocation).where(BudgetAllocation.user_id == self.uid)
        if up_to is not None:
            statement = statement.where(BudgetAllocation.month <= up_to)
        return list(remembered(self.db, ("allocations", self.uid, up_to), lambda: self.db.exec(statement).all()))

    def read(self, month: date, category_id: UUID) -> BudgetAllocation | None:
        return self.db.exec(
            select(BudgetAllocation).where(
                BudgetAllocation.user_id == self.uid,
                BudgetAllocation.month == month,
                BudgetAllocation.category_id == category_id,
            )
        ).first()

    def set(self, month: date, category_id: UUID, amount: Decimal) -> None:
        """Make the month's assigned amount for a category exactly `amount` (zero removes it)."""
        row = self.read(month, category_id)
        if amount == 0:
            if row is not None:
                self.db.delete(row)
        elif row is None:
            self.db.add(BudgetAllocation(user_id=self.uid, month=month, category_id=category_id, amount=amount))
        else:
            row.amount = amount
            self.db.add(row)
        self.db.flush()

    def add_many(self, rows: Iterable[tuple[date, UUID, Decimal]]) -> None:
        """Assign (month, category, amount) where nothing is assigned yet: nothing is read first and the rows are
        written together. The caller knows they are missing (a month being copied into, a ledger being restored)."""
        for month, category_id, amount in rows:
            if amount != 0:
                self.db.add(BudgetAllocation(user_id=self.uid, month=month, category_id=category_id, amount=amount))
        self.db.flush()

    def delete_for_category(self, category_id: UUID) -> None:
        for row in self.db.exec(
            select(BudgetAllocation).where(
                BudgetAllocation.user_id == self.uid, BudgetAllocation.category_id == category_id
            )
        ).all():
            self.db.delete(row)
        self.db.flush()

    def months_for_category(self, category_id: UUID) -> int:
        return len(
            self.db.exec(
                select(BudgetAllocation.id).where(
                    BudgetAllocation.user_id == self.uid, BudgetAllocation.category_id == category_id
                )
            ).all()
        )

    def merge_category(self, source: UUID, target: UUID) -> int:
        """The amounts planned for `source` become the target's (added to a month the target already has one for).
        Returns how many months moved. Nothing is committed."""
        rows = self.db.exec(
            select(BudgetAllocation).where(BudgetAllocation.user_id == self.uid, BudgetAllocation.category_id == source)
        ).all()
        for row in rows:
            existing = self.read(row.month, target)
            if existing is None:
                row.category_id = target
                self.db.add(row)
            else:
                existing.amount = existing.amount + row.amount
                self.db.add(existing)
                self.db.delete(row)
            self.db.flush()
        return len(rows)

    def uses_category(self, category_id: UUID) -> bool:
        return (
            self.db.exec(
                select(BudgetAllocation).where(
                    BudgetAllocation.user_id == self.uid, BudgetAllocation.category_id == category_id
                )
            ).first()
            is not None
        )
