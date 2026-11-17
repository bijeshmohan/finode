"""What the API takes and returns for income shared with contacts: whose it is and where it landed."""

from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ..clock import local_today
from .day import Day
from .transaction import _tidy_payee


def _positive(value: Decimal) -> Decimal:
    if value <= 0:
        raise ValueError("amount must be positive!")
    return value


class IncomePartIn(BaseModel):
    """An amount that belongs to a contact (or, in `received_by`, that a contact received for you)."""

    contact_id: UUID
    amount: Decimal = Field(decimal_places=8, max_digits=24)

    _positive = field_validator("amount")(_positive)


class IncomeDepositIn(BaseModel):
    """What landed in one of your accounts."""

    account_id: UUID
    amount: Decimal = Field(decimal_places=8, max_digits=24)

    _positive = field_validator("amount")(_positive)


class SharedIncomeCreate(BaseModel):
    """Money that came in, part of it not yours. Your income is the total less `theirs`; `deposits` and `received_by`
    must add up to the total (where the money landed: your accounts, or a contact who received it for you)."""

    description: str = Field(max_length=40)
    total_amount: Decimal = Field(decimal_places=8, max_digits=24)
    date: Day = Field(default_factory=local_today)
    # What your own part is earned under; none means Uncategorised.
    category_id: UUID | None = None
    # Parts that belong to contacts: you hold them (you owe each contact that much).
    theirs: list[IncomePartIn] = Field(default_factory=list)
    # Money a contact received for you: they owe you that much.
    received_by: list[IncomePartIn] = Field(default_factory=list)
    deposits: list[IncomeDepositIn] = Field(default_factory=list)

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        tidy = _tidy_payee(value)
        if not tidy:
            raise ValueError("shared income needs a description!")
        return tidy

    _positive = field_validator("total_amount")(_positive)


class IncomePartRead(BaseModel):
    contact_id: UUID
    name: str
    amount: Decimal


class IncomePreview(BaseModel):
    description: str
    total_amount: Decimal
    date: Date
    category_id: UUID | None
    your_income: Decimal
    theirs: list[IncomePartRead]
    received_by: list[IncomePartRead]
    deposits: list[IncomeDepositIn]


class SharedIncomeRead(IncomePreview):
    transaction_id: UUID
