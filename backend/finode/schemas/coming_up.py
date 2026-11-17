"""What is coming up: entries dated ahead and the occurrences recurring rules will record, in one list."""

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from .day import Day


class ComingUpLine(BaseModel):
    """One side of an entry or occurrence: an account, and the category when the account is Expenses or Income."""

    account_id: UUID
    category_id: UUID | None = None


class ComingUpItem(BaseModel):
    date: Day
    payee: str | None = None
    # What goes out (the debit side added up); for an income entry, what comes in.
    amount: Decimal
    income: bool = False
    # An entry already recorded (dated ahead), or a rule that will record it on its day.
    transaction_id: UUID | None = None
    recurring_id: UUID | None = None
    debits: list[ComingUpLine]
    credits: list[ComingUpLine]


class ComingUpRead(BaseModel):
    """Everything after today, up to `through`, that touches an account of the budget. `total` is what the entries
    come to, left out when money coming in and going out are mixed."""

    through: Day
    count: int
    total: Decimal | None = None
    items: list[ComingUpItem]
