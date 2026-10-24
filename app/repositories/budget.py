"""Persistence for the budget plan and goals, always filtered by the user's id."""

import builtins
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, select

from ..models.budget import BudgetAllocation, Goal, GoalAllocation
from .cache import remembered


class BudgetRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self, up_to: date | None = None) -> builtins.list[BudgetAllocation]:
        statement = select(BudgetAllocation).where(BudgetAllocation.user == self.uid)
        if up_to is not None:
            statement = statement.where(BudgetAllocation.month <= up_to)
        return list(remembered(self.db, ("allocations", self.uid, up_to), lambda: self.db.exec(statement).all()))

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

    def delete_for_account(self, account_id: UUID) -> None:
        for row in self.db.exec(
            select(BudgetAllocation).where(BudgetAllocation.user == self.uid, BudgetAllocation.account_id == account_id)
        ).all():
            self.db.delete(row)
        self.db.flush()

    def uses_account(self, account_id: UUID) -> bool:
        return (
            self.db.exec(
                select(BudgetAllocation).where(
                    BudgetAllocation.user == self.uid, BudgetAllocation.account_id == account_id
                )
            ).first()
            is not None
        )

    # ---- goals -----------------------------------------------------------------------------------

    def _goal_books(self) -> tuple[builtins.list[Goal], builtins.list[GoalAllocation]]:
        """The goals and everything set aside for them, in one round trip."""

        def load():
            rows = self.db.exec(
                select(Goal, GoalAllocation)
                .join(GoalAllocation, GoalAllocation.goal_id == Goal.gid, isouter=True)
                .where(Goal.user == self.uid)
            ).all()
            goals = list({g.gid: g for g, _ in rows}.values())
            return goals, [a for _, a in rows if a is not None]

        return remembered(self.db, ("goal-books", self.uid), load)

    def goals(self) -> builtins.list[Goal]:
        return list(self._goal_books()[0])

    def goal(self, gid: UUID) -> Goal | None:
        return next((g for g in self.goals() if g.gid == gid), None)

    def add_goal(self, name: str, amount: Decimal, target_date: date) -> Goal:
        goal = Goal(user=self.uid, name=name, amount=amount, target_date=target_date)
        self.db.add(goal)
        self.db.flush()
        return goal

    def save_goal(self, goal: Goal) -> None:
        self.db.add(goal)
        self.db.flush()

    def goal_allocations(self, up_to: date | None = None) -> builtins.list[GoalAllocation]:
        rows = self._goal_books()[1]
        return [r for r in rows if up_to is None or r.month <= up_to]

    def goal_assigned(self, month: date, goal_id: UUID) -> Decimal:
        return sum(
            (r.amount for r in self.goal_allocations() if r.month == month and r.goal_id == goal_id), Decimal("0.00")
        )

    def set_goal(self, month: date, goal_id: UUID, amount: Decimal) -> None:
        """Make the month's amount set aside for a goal exactly `amount` (zero removes it)."""
        row = self.db.exec(
            select(GoalAllocation).where(
                GoalAllocation.user == self.uid, GoalAllocation.month == month, GoalAllocation.goal_id == goal_id
            )
        ).first()
        if amount == 0:
            if row is not None:
                self.db.delete(row)
        elif row is None:
            self.db.add(GoalAllocation(user=self.uid, month=month, goal_id=goal_id, amount=amount))
        else:
            row.amount = amount
            self.db.add(row)
        self.db.flush()

    def delete_goal(self, goal_id: UUID) -> None:
        for row in self.db.exec(
            select(GoalAllocation).where(GoalAllocation.user == self.uid, GoalAllocation.goal_id == goal_id)
        ).all():
            self.db.delete(row)
        self.db.flush()
        goal = self.db.exec(select(Goal).where(Goal.user == self.uid, Goal.gid == goal_id)).first()
        if goal is not None:
            self.db.delete(goal)
        self.db.flush()
