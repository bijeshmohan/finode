from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from .day import Day


# Figures the budget computes. No digit limits: a sum of valid amounts may be longer than one amount can be, and a
# limit here would turn a long total into an error on every page.
Money = Field()


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


class GoalLine(BaseModel):
    """A goal: money set aside for something by a month. Not a category; nothing is spent from it directly (it hands its
    money to a category with `use_goal`)."""

    gid: UUID
    name: str
    # How much is needed, and the month it is needed by (the first day of it).
    amount: Decimal = Money
    target_date: Date
    # What was set aside (or taken back, or handed to a category, if negative) in the month, and what is saved in all, up to the month's end.
    assigned: Decimal = Money
    available: Decimal = Money
    # What this month asks of it (the by-date rule), what of that is still missing, and whether its month has passed with
    # money still short.
    needed: Decimal = Money
    underfunded: Decimal = Money
    overdue: bool = False


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
    # Goals are set aside for something and are not money to spend, so `assigned`, `activity`, `available`, `lines` and
    # Home's Left to spend leave them out; these are the goals and their sums.
    goals: list[GoalLine] = []
    goal_assigned: Decimal = Money
    goal_available: Decimal = Money
    # What the goals still need this month.
    goal_underfunded: Decimal = Money
    # Money in the budget's asset accounts and what is reserved for the cards' bills (sums of the cards' `owed`).
    # ready_to_assign = money_in_accounts - reserved_for_cards - available - goal_available - assigned_to_later_months.
    money_in_accounts: Decimal = Money
    reserved_for_cards: Decimal = Money
    cards: list[BudgetCard] = []
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
