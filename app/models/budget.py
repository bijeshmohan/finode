from datetime import date as Date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Index
from sqlmodel import Field

from .utils import Amount, TimestampMixin


class BudgetAllocation(TimestampMixin, table=True):
    """How much of a month's money the user assigned to a category (an Expenses account).

    Only the plan is stored: what is left to assign, what was spent and what is available are always
    derived from the ledger (see services/budget.py). `month` is the first day of the month and
    `amount` is in the user's default currency.
    """

    __tablename__ = "budget_allocations"
    __table_args__ = (Index("uq_budget_allocations", "user", "month", "account_id", unique=True),)

    bid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    month: Date
    account_id: UUID = Field(foreign_key="accounts.aid")
    amount: Decimal = Field(sa_type=Amount())


class BudgetTarget(TimestampMixin, table=True):
    """What a category should be funded with, so the budget can say how much is still missing.

    `kind` is `monthly` (assign `amount` every month), `refill` (keep `amount` available: assign what the
    carried-over money doesn't cover) or `by_date` (have `amount` available by `target_date`, saved up
    evenly month by month). Only the wish is stored; what is underfunded is derived (services/budget.py).
    """

    __tablename__ = "budget_targets"
    __table_args__ = (Index("uq_budget_targets", "user", "account_id", unique=True),)

    tgid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    account_id: UUID = Field(foreign_key="accounts.aid")
    kind: str = Field(max_length=16)
    amount: Decimal = Field(sa_type=Amount())
    target_date: Date | None = None
