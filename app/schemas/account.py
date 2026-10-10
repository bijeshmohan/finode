from datetime import date as Date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AccountBase(BaseModel):
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        if ":" in v:
            raise ValueError("name must not contain ':'!")
        return v


class AccountCreate(AccountBase):
    # Code of what the account holds. Defaults to what its parent holds (a top-level
    # parent: the user's default currency).
    commodity: str | None = Field(default=None, max_length=20)
    balance: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=8,
        max_digits=24,
    )
    # What the opening balance is worth in the opening-balances currency, when the account
    # holds something else and no price is known yet.
    balance_value: Decimal | None = Field(default=None, gt=0, decimal_places=8, max_digits=24)
    # Whether the account's money is part of the budget. Default: yes for a new asset account holding a currency.
    on_budget: bool | None = None


class AccountRead(AccountBase):
    aid: UUID
    # Code of what the account holds (e.g. "INR", "BTC"); for a root account, the default currency its total is in.
    commodity: str | None = None
    balance: Decimal = Field(decimal_places=8, max_digits=24)
    # True when part of the balance could not be valued because no price links it to the account's commodity.
    unpriced: bool = False
    # True when the account's money is part of the budget.
    on_budget: bool = False
    # An account outside the budget: the expense category that payments into it are budgeted under.
    payment_category_id: UUID | None = None
    # The day it was closed (no more postings; its history stays), or null while it is open.
    closed_on: Date | None = None
    created: datetime
    updated: datetime


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = None
    # Only while the account has no postings.
    commodity: str | None = Field(default=None, max_length=20)
    balance: Decimal | None = Field(
        default=None,
        decimal_places=8,
        max_digits=24,
    )
    balance_value: Decimal | None = Field(default=None, gt=0, decimal_places=8, max_digits=24)
    on_budget: bool | None = None
    # Send null to remove it; leave it out to keep it.
    payment_category_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v:
            raise ValueError("name must not be empty!")
        if ":" in v:
            raise ValueError("name must not contain ':'!")
        return v


class RegisterEntry(BaseModel):
    tid: UUID
    date: Date
    payee: str | None
    comment: str | None
    counter_accounts: list[str]
    change: Decimal = Field(decimal_places=8, max_digits=24)
    balance: Decimal = Field(decimal_places=8, max_digits=24)
    unpriced: bool = False


class HoldingRead(BaseModel):
    """An account holding something other than the default currency, valued in it."""

    commodity: str
    currency: str
    quantity: Decimal
    # Today's value in the default currency; None when no price is known.
    value: Decimal | None = None
    # What the postings to the account were worth when they were made.
    invested: Decimal | None = None
    gain: Decimal | None = None
    # The price behind `value` and the day it is from.
    rate: Decimal | None = None
    rate_as_of: Date | None = None
