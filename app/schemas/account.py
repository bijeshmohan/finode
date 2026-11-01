import unicodedata
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .transaction import RelatedRef


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
    # Liability accounts (a card, a loan): the day of the month a bill is closed and the day it is due. Both or neither;
    # 31 means the last day of a shorter month.
    statement_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        return clean_name(v)

    @model_validator(mode="after")
    def bill_days_come_together(self):
        if (self.statement_day is None) != (self.due_day is None):
            raise ValueError("give both the statement day and the due day, or neither!")
        return self


class AccountCreate(AccountBase):
    balance: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=8,
        max_digits=24,
    )
    # Whether the account's money is part of the budget. Default: yes for a new asset account.
    on_budget: bool | None = None


class AccountRead(AccountBase):
    id: UUID
    balance: Decimal  # a sum: no digit limits, see schemas/budget.py
    # True when the account's money is part of the budget.
    on_budget: bool = False
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
    statement_day: int | None = Field(default=None, ge=1, le=31)
    due_day: int | None = Field(default=None, ge=1, le=31)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str | None) -> str | None:
        return None if v is None else clean_name(v)


class RegisterEntry(BaseModel):
    transaction_id: UUID
    date: Date
    payee: str | None
    comment: str | None
    counter_accounts: list[str]
    change: Decimal
    balance: Decimal
    # The earlier entry this one is related to (a refund, a reversal), if any.
    related: RelatedRef | None = None


class CardBill(BaseModel):
    """A card's (or loan's) bill, worked out from its postings and its statement and due days. Nothing is stored."""

    account_id: UUID
    statement_day: int
    due_day: int
    # The latest statement date (the bill closed at the end of that day) and when that bill is due.
    statement_date: Date
    due_date: Date
    next_statement_date: Date
    # Negative once the due date has passed: -2 is two days overdue.
    days_to_due: int
    # What was owed when the bill closed (never below zero).
    statement_balance: Decimal = Field(description="a sum: no digit limits")
    # Payments and refunds since the statement, and purchases and charges since.
    paid_since: Decimal
    spent_since: Decimal
    # What is still to pay of that statement: its balance less what was paid since, never below zero.
    bill: Decimal
    # Everything owed today, the statement's bill and what was spent since.
    owed_total: Decimal


class AccountChangeRead(BaseModel):
    """One step in an account's life, with what it changed compared with the step before."""

    id: UUID
    account_id: UUID
    action: Literal["created", "updated", "closed", "reopened", "restored", "deleted"]
    at: datetime
    # "web", "api" or "mcp:<token name>"; None if unknown.
    via: str | None = None
    # The account as it stood after this step: name, path, note, budget flag, closing day.
    entry: dict[str, Any]
    # For an update: {field: {"from", "to"}} for name, path, note, on_budget and closed_on.
    changes: dict[str, Any] = Field(default_factory=dict)


class MergeRequest(BaseModel):
    # The account that takes over everything (this one is merged into it).
    into: UUID


class MergeResult(BaseModel):
    """What merging one account into another did (or, for a dry run, would do)."""

    dry_run: bool
    merged: bool
    source: str
    into: str
    # What the merged account held, now held by the other.
    balance_moved: Decimal
    entries_moved: int
    plan_months_moved: int
    recurring_rules_moved: int


class BalanceCheck(BaseModel):
    """A statement's balance set against the books on the same day (nothing is changed)."""

    account_id: UUID
    path: str
    as_of: Date
    # What the books say on that day (what is owed, for a card or loan), and what the statement says.
    book_balance: Decimal
    statement_balance: Decimal
    # Statement minus books: zero when they agree.
    difference: Decimal
    matches: bool
    # The entries of the last `days` days up to the day, oldest first.
    recent: list[RegisterEntry]
    # Entries in that window that are exactly as large as the difference: the likely extra or missing one.
    same_size_as_difference: list[RegisterEntry]


class ClosedAccount(BaseModel):
    """An account (or deleted-with-history category) that was closed: the outermost of its closed branch."""

    id: UUID
    name: str
    path: str
    root: str
    closed_on: Date


class DeletedAccount(BaseModel):
    """An account or category deleted for good that can still be restored."""

    id: UUID
    account_id: UUID
    at: datetime
    name: str | None = None
    path: str | None = None
    root: str | None = None
