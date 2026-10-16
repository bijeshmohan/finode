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
    balance: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=8,
        max_digits=24,
    )
    # Whether the account's money is part of the budget. Default: yes for a new asset account.
    on_budget: bool | None = None


class AccountRead(AccountBase):
    aid: UUID
    balance: Decimal = Field(decimal_places=8, max_digits=24)
    # True when the account's money is part of the budget.
    on_budget: bool = False
    # An account outside the budget: the expense category that payments into it are budgeted under.
    payment_category_id: UUID | None = None
    # The day it was closed (no more postings; its history stays), or null while it is open.
    closed_on: Date | None = None
    # Listed at the top of the accounts page.
    pinned: bool = False
    # The place among its siblings when ordered by hand (0 first); null while they are in alphabetical order.
    position: int | None = None
    created: datetime
    updated: datetime


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = None
    balance: Decimal | None = Field(
        default=None,
        decimal_places=8,
        max_digits=24,
    )
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
