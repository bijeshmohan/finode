from datetime import date as Date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Index
from sqlmodel import Field

from .utils import Amount, TimestampMixin


class BudgetAllocation(TimestampMixin, table=True):
    """How much of a month's money the user assigned to a budget category.

    Only the plan is stored: what is left to assign, what was spent and what is available are always
    derived from the ledger (see services/budget.py). `month` is the first day of the month and
    `amount` is in the user's default currency.
    """

    __tablename__ = "budget_allocations"
    __table_args__ = (Index("uq_budget_allocations_category", "user_id", "month", "category_id", unique=True),)

    bid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    month: Date
    category_id: UUID = Field(foreign_key="budget_categories.bcid", index=True)
    amount: Decimal = Field(sa_type=Amount())


class Goal(TimestampMixin, table=True):
    """Money the user is saving for something by a month: not an account and not a category.

    Only the wish is stored (a name, how much and the month it is needed by); what is saved is the sum of its
    `GoalAllocation` rows up to a month. Spending on what a goal was for is recorded against an ordinary category,
    and the goal then hands its money to that category (`BudgetService.use_goal`).
    """

    __tablename__ = "goals"

    gid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=80)
    amount: Decimal = Field(sa_type=Amount())
    target_date: Date


class GoalAllocation(TimestampMixin, table=True):
    """What was set aside for a goal in a month (negative when money was taken back or handed to a category)."""

    __tablename__ = "goal_allocations"
    __table_args__ = (Index("uq_goal_allocations", "user_id", "month", "goal_id", unique=True),)

    gaid: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    month: Date
    goal_id: UUID = Field(foreign_key="goals.gid", index=True)
    amount: Decimal = Field(sa_type=Amount())
