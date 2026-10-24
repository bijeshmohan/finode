from datetime import date as Date, datetime
from decimal import Decimal
from uuid import UUID

import unicodedata

from pydantic import BaseModel, Field, field_validator


def clean_name(value: str) -> str:
    """An account's name as it will be kept: trimmed, with something visible in it, on one line, without ':' (the path
    separator). Zero-width and other invisible characters do not count as a name."""
    value = value.strip()
    if not value or all(unicodedata.category(c) in ("Cf", "Zs", "Zl", "Zp") for c in value):
        raise ValueError("name must not be empty!")
    if any(unicodedata.category(c) == "Cc" for c in value):
        raise ValueError("name must be on one line, without control characters!")
    if ":" in value:
        raise ValueError("name must not contain ':'!")
    return value


class AccountBase(BaseModel):
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        return clean_name(v)


class AccountCreate(AccountBase):
    balance: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=8,
        max_digits=24,
    )
    # Whether the account's money is part of the budget. Default: yes for a new asset account.
    on_budget: bool | None = None
    # For an account outside the budget: the expense category that payments into it are budgeted under.
    payment_category_id: UUID | None = None


class AccountRead(AccountBase):
    aid: UUID
    balance: Decimal  # a sum: no digit limits, see schemas/budget.py
    # True when the account's money is part of the budget.
    on_budget: bool = False
    # An account outside the budget: the expense category that payments into it are budgeted under.
    payment_category_id: UUID | None = None
    # The day it was closed (no more postings; its history stays), or null while it is open.
    closed_on: Date | None = None
    # Set on the built-in groups (Bank Accounts, Cash, Investments, Credit Cards, Loans); they cannot be changed or removed.
    system_key: str | None = None
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
        return None if v is None else clean_name(v)


class RegisterEntry(BaseModel):
    tid: UUID
    date: Date
    payee: str | None
    comment: str | None
    counter_accounts: list[str]
    change: Decimal
    balance: Decimal


class ClosedAccount(BaseModel):
    """An account (or deleted-with-history category) that was closed: the outermost of its closed branch."""

    aid: UUID
    name: str
    path: str
    root: str
    closed_on: Date


class DeletedAccount(BaseModel):
    """An account or category deleted for good that can still be restored."""

    did: UUID
    account_id: UUID
    at: datetime
    name: str | None = None
    path: str | None = None
    root: str | None = None
