"""What the API takes and returns for the budget: a month's lines and cards, and assigning, moving and copying."""

from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from .day import Day

# Figures the budget computes. No digit limits: a sum of valid amounts may be longer than one amount can be, and a
# limit here would turn a long total into an error on every page.
Money = Field()


class BudgetCard(BaseModel):
    """A credit card (or other liability that is part of the budget): what is set aside to pay it."""

    account_id: UUID
    path: str
    # What is owed on it at the end of the month; that much of the budget's money is reserved for the bill and
    # is already out of ready_to_assign. Zero for a card in credit.
    owed: Decimal = Money
    # Added to the card this month (purchases) and paid off it this month.
    charged: Decimal = Money
    paid: Decimal = Money


class BudgetLine(BaseModel):
    category_id: UUID
    name: str
    # The category's icon (finode/category_icons.py).
    icon: str
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
    # The user's currency.
    currency: str
    # Money in the budget's accounts that is not assigned to a category yet. Negative when more is assigned than there is.
    ready_to_assign: Decimal = Money
    # Money in the budget's accounts (credit cards counted as negative).
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
    # The accounts whose money is budgeted: every account of the four types.
    budget_accounts: list[str]
    lines: list[BudgetLine]


class BudgetAssign(BaseModel):
    # Any day in the month.
    month: Day | None = None
    # The month's total for the category, not an addition to it.
    amount: Decimal = Field(decimal_places=8, max_digits=24)


Amount = Field(decimal_places=8, max_digits=24)


class BudgetMove(BaseModel):
    """Take money from one category's available and give it to another, in a month."""

    month: Day | None = None
    from_category: UUID
    to_category: UUID
    amount: Decimal = Amount


class BudgetCopy(BaseModel):
    """Assign a month what each category got the month before, where nothing is assigned yet."""

    month: Day | None = None
