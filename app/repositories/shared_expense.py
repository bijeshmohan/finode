"""Persistence for shared expenses and their shares and contributions, always filtered by the user's id."""

import builtins
from uuid import UUID

from sqlmodel import Session, col, select

from ..models.contact import ExpenseContribution, ExpenseShare, SharedExpense


class SharedExpenseRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def read(self, expense_id: UUID, lock: bool = False) -> SharedExpense | None:
        """One expense; `lock` takes a row lock on Postgres so two confirmations of it queue up."""
        statement = select(SharedExpense).where(SharedExpense.user_id == self.uid, SharedExpense.id == expense_id)
        if lock:
            statement = statement.with_for_update()
        return self.db.exec(statement).first()

    def list(self, status: str | None = None) -> builtins.list[SharedExpense]:
        statement = select(SharedExpense).where(SharedExpense.user_id == self.uid)
        if status is not None:
            statement = statement.where(SharedExpense.status == status)
        return list(self.db.exec(statement.order_by(col(SharedExpense.date).desc(), col(SharedExpense.created).desc())))

    def by_transaction(self, transaction_id: UUID) -> SharedExpense | None:
        return self.db.exec(
            select(SharedExpense).where(
                SharedExpense.user_id == self.uid, SharedExpense.transaction_id == transaction_id
            )
        ).first()

    def shares(self, expense_id: UUID) -> builtins.list[ExpenseShare]:
        return list(
            self.db.exec(
                select(ExpenseShare)
                .where(ExpenseShare.user_id == self.uid, ExpenseShare.shared_expense_id == expense_id)
                .order_by(col(ExpenseShare.created), col(ExpenseShare.id))
            )
        )

    def contributions(self, expense_id: UUID) -> builtins.list[ExpenseContribution]:
        return list(
            self.db.exec(
                select(ExpenseContribution)
                .where(ExpenseContribution.user_id == self.uid, ExpenseContribution.shared_expense_id == expense_id)
                .order_by(col(ExpenseContribution.created), col(ExpenseContribution.id))
            )
        )

    def add(self, expense: SharedExpense) -> SharedExpense:
        self.db.add(expense)
        self.db.flush()
        return expense

    def clear_children(self, expense_id: UUID) -> None:
        for row in (*self.shares(expense_id), *self.contributions(expense_id)):
            self.db.delete(row)
        self.db.flush()

    def delete(self, expense: SharedExpense) -> None:
        self.clear_children(expense.id)
        self.db.delete(expense)
        self.db.flush()

    def uses_contact(self, contact_id: UUID) -> bool:
        """Whether any shared expense, draft or confirmed, names the contact."""
        shares = self.db.exec(
            select(ExpenseShare.id).where(ExpenseShare.user_id == self.uid, ExpenseShare.contact_id == contact_id)
        ).first()
        paid = self.db.exec(
            select(ExpenseContribution.id).where(
                ExpenseContribution.user_id == self.uid, ExpenseContribution.contact_id == contact_id
            )
        ).first()
        return shares is not None or paid is not None
