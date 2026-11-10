from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from .budget import BudgetLeftOut, BudgetUncategorised


class TodoRule(BaseModel):
    """A running recurring rule that could not be recorded (its account can no longer be posted to, say)."""

    recurring_id: UUID
    name: str
    error: str


class TodoCard(BaseModel):
    """A card's (or loan's) bill that is due within a few days or overdue, and still not paid."""

    account_id: UUID
    # The account's path, e.g. Liabilities:Credit Cards:Visa.
    path: str
    bill: Decimal
    due_date: Date
    # Negative once overdue: -2 is two days overdue.
    days_to_due: int


class TodoRead(BaseModel):
    """What needs a decision now. Nothing is stored: each item is a fact about the books and goes when it is fixed."""

    # Payments into an account outside the budget that no category took (this month).
    uncategorised: list[BudgetUncategorised] = []
    # Accounts that pay for things but are not part of the budget (this month).
    left_out_accounts: list[BudgetLeftOut] = []
    failing_rules: list[TodoRule] = []
    # Bills due within a few days or overdue (one each).
    card_bills: list[TodoCard] = []
    # The payments count as one thing; each account, rule and bill is one.
    count: int = 0
