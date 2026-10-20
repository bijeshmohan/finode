from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from .day import Day


# Figures the budget computes. No digit limits: a sum of valid amounts may be longer than one amount can be, and a
# limit here would turn a long total into an error on every page.
Money = Field()


TARGET_KINDS = ("monthly", "weekly", "refill", "by_date", "yearly")


class BudgetTargetRead(BaseModel):
    # monthly: assign `amount` every month; weekly: `amount` every week, on `weekday` (0 = Monday); refill: keep `amount`
    # available; by_date: have `amount` available by `target_date`; yearly: the same every year, in `target_date`'s month.
    kind: str
    amount: Decimal = Money
    target_date: Date | None = None
    weekday: int | None = None


class BudgetTargetSet(BaseModel):
    kind: str
    amount: Decimal = Field(gt=0, decimal_places=8, max_digits=24)
    target_date: Day | None = None
    weekday: int | None = Field(default=None, ge=0, le=6)


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


class BudgetWeek(BaseModel):
    """One week of a category with a weekly target (weeks start on the target's day), clipped to the month."""

    start: Date
    end: Date
    # What was spent in it, and what the target allows for it. None for the days before the month's first such
    # day: that week was funded last month.
    spent: Decimal = Money
    allowance: Decimal | None = None
    # The week that includes today.
    current: bool = False


class BudgetLine(BaseModel):
    aid: UUID
    # The category's name, and its path below Expenses, e.g. "Food:Groceries".
    name: str
    path: str
    # Levels below Expenses (Expenses:Food is 1).
    depth: int
    # True for a category with subcategories: its figures are the sum of theirs.
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
    # is still missing (zero when funded or without a target). A group sums its subcategories' missing money.
    target: BudgetTargetRead | None = None
    needed: Decimal = Money
    underfunded: Decimal = Money
    # A "by a month" target whose month has passed and is still short.
    overdue: bool = False
    # The category's note (the account's details), if it has one.
    note: str | None = None
    # With a weekly target: the month week by week.
    weeks: list[BudgetWeek] = []


class BudgetSaving(BaseModel):
    """A line of the plan's Save section: an asset outside the budget that the person plans to save into."""

    aid: UUID
    name: str
    # Its path below Assets, e.g. "Investments:Mutual Funds".
    path: str
    # What was assigned to it in the month, what was moved into it from the budget's accounts (withdrawals do not
    # subtract) and what is left to move, counting everything assigned and moved in earlier months too.
    assigned: Decimal = Money
    activity: Decimal = Money
    available: Decimal = Money
    # What the account holds at the end of the month.
    balance: Decimal = Money
    closed: bool = False
    # Its target (the same kinds as a category's), what it needs from this month's assigning and what is still missing.
    target: BudgetTargetRead | None = None
    needed: Decimal = Money
    underfunded: Decimal = Money
    overdue: bool = False
    note: str | None = None


class BudgetRead(BaseModel):
    # First day of the month the figures are for; they count everything up to its last day.
    month: Date
    # The user's currency.
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
    # The Save section: what was assigned to the accounts planned for saving, what was moved into them and what is
    # still to move (their `available`), totals of the lines in `saving`. `assigned`, `activity` and `available`
    # above are the Spend section's only.
    saving: list[BudgetSaving] = []
    saving_assigned: Decimal = Money
    saving_activity: Decimal = Money
    saving_available: Decimal = Money
    # Money in the budget's asset accounts and what is reserved for the cards' bills (sums of the cards' `owed`).
    # ready_to_assign = money_in_accounts - reserved_for_cards - available - saving_available - assigned_to_later_months.
    money_in_accounts: Decimal = Money
    reserved_for_cards: Decimal = Money
    cards: list[BudgetCard] = []
    # What the targets still need this month, all categories.
    underfunded: Decimal = Money
    # Spending this month that is not counted in the categories because it was paid from accounts outside the
    # budget (a credit card that was never switched on, for example), and those accounts.
    left_out: Decimal = Money
    left_out_accounts: list[BudgetLeftOut] = []
    # The accounts whose money is budgeted, and the flagged ones left out (accounts with sub-accounts).
    budget_accounts: list[str]
    ignored_accounts: list[str]
    lines: list[BudgetLine]


class BudgetAssign(BaseModel):
    # Any day in the month.
    month: Day | None = None
    # The month's total for the category, not an addition to it.
    amount: Decimal = Field(decimal_places=8, max_digits=24)
