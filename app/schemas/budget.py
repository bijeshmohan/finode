from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


Money = Field(decimal_places=8, max_digits=24)


TARGET_KINDS = ("monthly", "refill", "by_date")


class BudgetTargetRead(BaseModel):
    # monthly: assign `amount` every month; refill: keep `amount` available; by_date: have `amount` available by `target_date`.
    kind: str
    amount: Decimal = Money
    target_date: Date | None = None


class BudgetTargetSet(BaseModel):
    kind: str
    amount: Decimal = Field(gt=0, decimal_places=8, max_digits=24)
    target_date: Date | None = None


class BudgetLeftOut(BaseModel):
    # An account that could be part of the budget but is not, and what it paid for this month.
    aid: UUID
    path: str
    entries: int
    spent: Decimal = Money


class BudgetCard(BaseModel):
    """A credit card (or other liability that is part of the budget): what is set aside to pay it."""

    aid: UUID
    path: str
    # What is owed on it at the end of the month; that much of the budget's money is reserved for the bill and
    # is already out of ready_to_assign. Zero for a card in credit.
    owed: Decimal = Money
    # Added to the card this month (purchases) and paid off it this month.
    charged: Decimal = Money
    paid: Decimal = Money


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
    # The category's target (none on groups), what it needs from this month's assigning, and what of that
    # is still missing (zero when funded or without a target). A group sums its sub-categories' missing money.
    target: BudgetTargetRead | None = None
    needed: Decimal = Money
    underfunded: Decimal = Money


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
    # Money already assigned to months after this one: it is out of ready_to_assign now.
    assigned_to_later_months: Decimal = Money
    # What copying last month's assignments would assign here (categories with nothing assigned this month yet).
    copyable: Decimal = Money
    # Money in the budget's asset accounts and what is reserved for the cards' bills (sums of the cards' `owed`).
    # ready_to_assign = money_in_accounts - reserved_for_cards - available - assigned_to_later_months.
    money_in_accounts: Decimal = Money
    reserved_for_cards: Decimal = Money
    cards: list[BudgetCard] = []
    # What the targets still need this month, all categories.
    underfunded: Decimal = Money
    # Spending this month that is not counted in the categories because it was paid from accounts outside the
    # budget (a credit card that was never switched on, for example), and those accounts.
    left_out: Decimal = Money
    left_out_accounts: list[BudgetLeftOut] = []
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


class BudgetFund(BaseModel):
    month: Date | None = None


class BudgetCopy(BaseModel):
    # Any day in the month to copy into (this month by default).
    month: Date | None = None


class BudgetMove(BaseModel):
    month: Date | None = None
    from_category: UUID
    to_category: UUID
    amount: Decimal = Field(gt=0, decimal_places=8, max_digits=24)
