"""The budget plan: what a person assigned to each category in each month."""

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

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    month: Date
    category_id: UUID = Field(foreign_key="budget_categories.id", index=True)
    amount: Decimal = Field(sa_type=Amount())
