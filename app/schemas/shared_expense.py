"""What the API takes and returns for an expense split with contacts: who shares it, who paid, what it records."""

from datetime import date as Date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..clock import local_today
from ..models.transaction import PostingSide
from .day import Day
from .transaction import _tidy_payee

SplitMethod = Literal["equal", "exact", "percentage", "shares"]
ExpenseStatus = Literal["draft", "confirmed"]


def _positive(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("amount must be positive!")
    return value


class ParticipantIn(BaseModel):
    """Who shares the expense: you (`is_self`) or a contact. `value` is what the split method needs: nothing for an
    equal split, the weight for `shares`, the percentage for `percentage` or the amount for `exact`."""

    is_self: bool = False
    contact_id: UUID | None = None
    value: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)

    @model_validator(mode="after")
    def _one_of_you_or_a_contact(self) -> ParticipantIn:
        if self.is_self == (self.contact_id is not None):
            raise ValueError("a participant is either you (is_self) or a contact (contact_id)!")
        return self


class ContributionIn(BaseModel):
    """What a contact paid towards the bill (your own payments go in `payments`)."""

    contact_id: UUID
    amount: Decimal = Field(decimal_places=8, max_digits=24)

    _positive = field_validator("amount")(_positive)


class PaymentIn(BaseModel):
    """What you paid, from which of your accounts."""

    account_id: UUID
    amount: Decimal = Field(decimal_places=8, max_digits=24)

    _positive = field_validator("amount")(_positive)


class _ExpenseFields(BaseModel):
    description: str = Field(max_length=40)
    total_amount: Decimal = Field(decimal_places=8, max_digits=24)
    date: Day = Field(default_factory=local_today)
    # What your own share is spent under; none means Uncategorised.
    category_id: UUID | None = None
    split_method: SplitMethod = "equal"
    participants: list[ParticipantIn] = Field(min_length=2)
    contributions: list[ContributionIn] = Field(default_factory=list)
    payments: list[PaymentIn] = Field(default_factory=list)

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        tidy = _tidy_payee(value)
        if not tidy:
            raise ValueError("a shared expense needs a description!")
        return tidy

    _positive = field_validator("total_amount")(_positive)


class SharedExpenseCreate(_ExpenseFields):
    pass


class SharedExpenseUpdate(BaseModel):
    """Change a draft: only what is sent changes (a list is replaced as a whole)."""

    description: str | None = Field(default=None, max_length=40)
    total_amount: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    date: Day | None = None
    category_id: UUID | None = None
    split_method: SplitMethod | None = None
    participants: list[ParticipantIn] | None = Field(default=None, min_length=2)
    contributions: list[ContributionIn] | None = None
    payments: list[PaymentIn] | None = None


class ShareRead(BaseModel):
    is_self: bool
    contact_id: UUID | None
    name: str
    share_amount: Decimal
    # The percentage, weight or amount the share was worked out from.
    share_value: Decimal | None
    contributed: Decimal
    # contributed less share: above zero they paid more than their share, below zero less.
    net: Decimal


class ContributionRead(BaseModel):
    is_self: bool
    contact_id: UUID | None
    account_id: UUID | None
    amount: Decimal


class LineRead(BaseModel):
    """One line of the ledger entry that confirming will record (or recorded)."""

    account_id: UUID
    category_id: UUID | None
    side: PostingSide
    amount: Decimal


class OwedRead(BaseModel):
    contact_id: UUID
    name: str
    direction: Literal["receivable", "payable"]
    amount: Decimal


class ExpensePreview(BaseModel):
    description: str
    total_amount: Decimal
    date: Date
    category_id: UUID | None
    split_method: SplitMethod
    # What your own share comes to: the only part that counts against your budget.
    user_share: Decimal
    user_paid: Decimal
    # What is paid in all, and what is still unpaid (confirming needs this to be zero).
    funded: Decimal
    unfunded: Decimal
    shares: list[ShareRead]
    contributions: list[ContributionRead]
    # The ledger lines it will make (empty while the bill is not fully paid for) and what is left owed either way.
    lines: list[LineRead]
    owed: list[OwedRead]


class SharedExpenseRead(ExpensePreview):
    id: UUID
    status: ExpenseStatus
    # The ledger entry, once confirmed.
    transaction_id: UUID | None
