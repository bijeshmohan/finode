from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


Money = Field(decimal_places=8, max_digits=24)


class BudgetLine(BaseModel):
    aid: UUID
    # The category's name, and its path below Expenses, e.g. "Food:Groceries".
    name: str
    path: str
    # Levels below Expenses (Expenses:Food is 1).
    depth: int
    # True for a category with sub-categories: its figures are the sum of theirs.
    group: bool = False
    # What was assigned in the month, what was spent (refunds subtract) and what is left,
    # counting everything assigned and spent in earlier months too.
    assigned: Decimal = Money
    activity: Decimal = Money
    available: Decimal = Money
    # What the category was overspent by at the end of the previous month. It started this month at zero,
    # and that amount was taken out of what is ready to assign.
    overspent_last_month: Decimal = Money


class BudgetRead(BaseModel):
    # First day of the month the figures are for; they count everything up to its last day.
    month: Date
    # The user's default currency: the budget works in it.
    currency: str
    # Money in the budget's accounts that is not assigned to a category yet. Negative when more is assigned than there is.
    ready_to_assign: Decimal = Money
    # Money in the budget's accounts (cards and loans counted as negative).
    cash: Decimal = Money
    assigned: Decimal = Money
    activity: Decimal = Money
    available: Decimal = Money
    # Overspending in the previous month (all categories): already taken out of ready_to_assign.
    overspent_last_month: Decimal = Money
    # True when some spending could not be converted to the currency because no price links them.
    unpriced: bool = False
    # The accounts whose money is budgeted, and the flagged ones left out (another currency, sub-accounts).
    budget_accounts: list[str]
    ignored_accounts: list[str]
    lines: list[BudgetLine]


class BudgetAssign(BaseModel):
    # Any day in the month.
    month: Date | None = None
    # The month's total for the category, not an addition to it.
    amount: Decimal = Field(decimal_places=8, max_digits=24)


class BudgetMove(BaseModel):
    month: Date | None = None
    from_category: UUID
    to_category: UUID
    amount: Decimal = Field(gt=0, decimal_places=8, max_digits=24)
