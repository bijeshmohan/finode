from uuid import UUID

from pydantic import BaseModel

from .budget import BudgetLeftOut, BudgetUncategorised


class TodoRule(BaseModel):
    """A running recurring rule that could not be recorded (its account can no longer be posted to, say)."""

    rid: UUID
    name: str
    error: str


class TodoRead(BaseModel):
    """What needs a decision now. Nothing is stored: each item is a fact about the books and goes when it is fixed."""

    # Payments into an account outside the budget that no category took (this month).
    uncategorised: list[BudgetUncategorised] = []
    # Accounts that pay for things but are not part of the budget (this month).
    left_out_accounts: list[BudgetLeftOut] = []
    failing_rules: list[TodoRule] = []
    # The payments count as one thing; each account and each rule is one.
    count: int = 0
