from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, select

from ..models.budget import BudgetAllocation, BudgetTarget


class BudgetRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self, up_to: date | None = None) -> list[BudgetAllocation]:
        statement = select(BudgetAllocation).where(BudgetAllocation.user == self.uid)
        if up_to is not None:
            statement = statement.where(BudgetAllocation.month <= up_to)
        return self.db.exec(statement).all()

    def read(self, month: date, account_id: UUID) -> BudgetAllocation | None:
        return self.db.exec(
            select(BudgetAllocation).where(
                BudgetAllocation.user == self.uid,
                BudgetAllocation.month == month,
                BudgetAllocation.account_id == account_id,
            )
        ).first()

    def set(self, month: date, account_id: UUID, amount: Decimal) -> None:
        """Make the month's assigned amount for a category exactly `amount` (zero removes it)."""
        row = self.read(month, account_id)
        if amount == 0:
            if row is not None:
                self.db.delete(row)
        elif row is None:
            self.db.add(BudgetAllocation(user=self.uid, month=month, account_id=account_id, amount=amount))
        else:
            row.amount = amount
            self.db.add(row)
        self.db.flush()

    def targets(self) -> dict[UUID, BudgetTarget]:
        rows = self.db.exec(select(BudgetTarget).where(BudgetTarget.user == self.uid)).all()
        return {r.account_id: r for r in rows}

    def set_target(self, account_id: UUID, kind: str, amount: Decimal, target_date: date | None) -> None:
        row = self.targets().get(account_id)
        if row is None:
            row = BudgetTarget(user=self.uid, account_id=account_id, kind=kind, amount=amount, target_date=target_date)
        else:
            row.kind, row.amount, row.target_date = kind, amount, target_date
        self.db.add(row)
        self.db.flush()

    def clear_target(self, account_id: UUID) -> None:
        row = self.targets().get(account_id)
        if row is not None:
            self.db.delete(row)
            self.db.flush()

    def delete_for_account(self, account_id: UUID) -> None:
        self.clear_target(account_id)
        for row in self.db.exec(
            select(BudgetAllocation).where(
                BudgetAllocation.user == self.uid, BudgetAllocation.account_id == account_id
            )
        ).all():
            self.db.delete(row)
        self.db.flush()

    def uses_account(self, account_id: UUID) -> bool:
        return self.db.exec(
            select(BudgetAllocation).where(
                BudgetAllocation.user == self.uid, BudgetAllocation.account_id == account_id
            )
        ).first() is not None
