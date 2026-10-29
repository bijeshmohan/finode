from datetime import date as Date
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field

from .utils import TimestampMixin


class CategoryKind(StrEnum):
    SPENDING = "spending"
    EARNING = "earning"


class BudgetCategory(TimestampMixin, table=True):
    """What money was for (Groceries, EMI, Salary): the budget's own list, apart from the books' accounts.

    A category is a label on the lines of a transaction (`postings.category_id`) and the thing the budget plans against
    (`budget_allocations.category_id`). Two kinds: spending (an envelope) and earning (a label for reports). It sits at
    most two levels deep: a group (no parent) and the categories inside it. The Income or Expenses accounts the books
    need on the other side of an entry point back at it (`accounts.category_id`); several accounts may share one.
    """

    __tablename__ = "budget_categories"
    __table_args__ = (
        CheckConstraint("kind IN ('spending', 'earning')", name="ck_budget_categories_kind"),
        # The built-in Uncategorised of each kind, one per person.
        Index(
            "uq_budget_categories_user_system_key",
            "user",
            "system_key",
            unique=True,
            sqlite_where=text("system_key IS NOT NULL"),
            postgresql_where=text("system_key IS NOT NULL"),
        ),
    )

    bcid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    kind: str = Field(max_length=8)
    parent_id: UUID | None = Field(default=None, foreign_key="budget_categories.bcid", nullable=True)
    # Set on the built-in Uncategorised categories ("uncategorised.spending", "uncategorised.earning").
    system_key: str | None = Field(default=None, max_length=40)
    # The day it was closed: no longer offered, history kept.
    closed_on: Date | None = Field(default=None)
