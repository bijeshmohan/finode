import unicodedata
from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ..clock import local_today
from .day import Day

MAX_NAME = 30  # "Due from " takes 9 of an account name's 40 characters


def clean_contact_name(value: str) -> str:
    """A contact's name as kept: trimmed, visible, on one line, without ':' (it becomes part of two account names)."""
    value = value.strip()
    if not value or all(unicodedata.category(c) in ("Cf", "Zs", "Zl", "Zp") for c in value):
        raise ValueError("name must not be empty!")
    if any(unicodedata.category(c) == "Cc" for c in value):
        raise ValueError("name must be on one line, without control characters!")
    if ":" in value:
        raise ValueError("name must not contain ':'!")
    return value


def _tidy(value: str | None) -> str | None:
    """A blank detail is none."""
    return (value or "").strip() or None


class ContactBase(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("email", "phone", "notes")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return _tidy(value)


class ContactCreate(ContactBase):
    name: str = Field(max_length=MAX_NAME)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_contact_name(value)


class ContactUpdate(ContactBase):
    # Only what is sent changes; null clears email, phone and notes.
    name: str | None = Field(default=None, max_length=MAX_NAME)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name must not be empty!")
        return clean_contact_name(value)


class ContactRead(ContactBase):
    id: UUID
    name: str
    archived: bool
    archived_at: datetime | None
    # The ledger accounts behind the contact: "Due from X" (they owe you) and "Due to X" (you owe them).
    receivable_account_id: UUID
    payable_account_id: UUID
    # What the books say (entries dated ahead included): `receivable` is what they owe you, `payable` what you owe them,
    # `net` the two together (above zero they owe you).
    receivable: Decimal
    payable: Decimal
    net: Decimal
    # The day of the latest thing done with them.
    last_activity: Date | None


class ContactDeleteResult(BaseModel):
    # "deleted" (no money ever moved: gone for good) or "archived" (it has history: kept, no longer offered).
    outcome: Literal["deleted", "archived"]
    contact: ContactRead


TransferDirection = Literal["sent", "received"]
TransferPurpose = Literal["loan", "borrowing", "advance", "gift"]


class TransferCreate(BaseModel):
    """Money sent to a contact (a loan, an advance, a gift) or received from one (a borrowing, an advance, a gift)."""

    direction: TransferDirection
    purpose: TransferPurpose
    amount: Decimal = Field(decimal_places=8, max_digits=24)
    date: Day = Field(default_factory=local_today)
    # Your own account the money leaves (sent) or arrives in (received).
    account_id: UUID
    description: str | None = Field(default=None, max_length=200)
    # A gift is spending (sent) or income (received) under this category; none means Uncategorised. Other purposes take none.
    category_id: UUID | None = None

    @field_validator("amount")
    @classmethod
    def _positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount must be positive!")
        return value

    @field_validator("description")
    @classmethod
    def _tidy_description(cls, value: str | None) -> str | None:
        return _tidy(value)


class TransferRead(BaseModel):
    # The ledger entry that records it.
    id: UUID
    contact_id: UUID
    direction: TransferDirection
    purpose: TransferPurpose
    amount: Decimal
    date: Date
    account_id: UUID | None
    description: str | None
    # The amount it left owed either way (none for a gift).
    obligation_id: UUID | None


ObligationDirection = Literal["receivable", "payable"]
ObligationSource = Literal["shared_expense", "loan", "borrowing", "advance"]


class ObligationRead(BaseModel):
    id: UUID
    contact_id: UUID
    source_transaction_id: UUID
    source_type: ObligationSource
    direction: ObligationDirection
    # What the entry was called ("Dinner", "Personal loan") and when it happened.
    description: str | None
    date: Date
    original_amount: Decimal
    settled_amount: Decimal
    outstanding_amount: Decimal
    status: Literal["open", "partially_settled", "settled"]


SettlementDirection = Literal["received", "sent"]
ExcessUse = Literal["loan", "borrowing", "advance", "gift"]


class AllocationIn(BaseModel):
    obligation_id: UUID
    amount: Decimal = Field(decimal_places=8, max_digits=24)

    @field_validator("amount")
    @classmethod
    def _positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount must be positive!")
        return value


class SettlementCreate(BaseModel):
    """Money a contact pays back (`received`, clearing what they owe you) or you pay them (`sent`, clearing what you
    owe them)."""

    direction: SettlementDirection
    amount: Decimal = Field(decimal_places=8, max_digits=24)
    date: Day = Field(default_factory=local_today)
    # Your own account the money arrives in (received) or leaves (sent).
    account_id: UUID
    # fifo: the oldest amounts owed are cleared first. manual: `allocations` say which and how much.
    allocation_method: Literal["fifo", "manual"] = "fifo"
    allocations: list[AllocationIn] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=200)
    # More than is owed is never swallowed: say what the rest is. Received: `borrowing` or `advance` (you now owe them)
    # or `gift`; sent: `loan` or `advance` (they now owe you) or `gift`.
    excess_as: ExcessUse | None = None
    # A gift's category (none means Uncategorised).
    excess_category_id: UUID | None = None

    @field_validator("amount")
    @classmethod
    def _positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount must be positive!")
        return value

    @field_validator("description")
    @classmethod
    def _tidy_description(cls, value: str | None) -> str | None:
        return _tidy(value)


class AllocationRead(BaseModel):
    obligation_id: UUID
    # What was owed on it before this settlement, how much this one clears and what is left.
    outstanding_before: Decimal
    amount: Decimal
    outstanding_after: Decimal


class SettlementPreview(BaseModel):
    direction: SettlementDirection
    amount: Decimal
    allocations: list[AllocationRead]
    # What the settlement clears, what is left over and what that was said to be.
    allocated: Decimal
    excess: Decimal
    excess_as: ExcessUse | None
    # Still owed on this side after the settlement.
    remaining: Decimal


class SettlementRead(BaseModel):
    # The ledger entry that records it.
    id: UUID
    contact_id: UUID
    direction: SettlementDirection
    amount: Decimal
    date: Date
    account_id: UUID | None
    description: str | None
    allocations: list[AllocationRead]
    excess: Decimal
    excess_as: ExcessUse | None
    # The new amount owed the excess left, when it became a loan, borrowing or advance.
    excess_obligation_id: UUID | None


ActivityPurpose = Literal["loan", "borrowing", "advance", "gift", "expense", "settlement"]


class ActivityRead(BaseModel):
    transaction_id: UUID
    date: Date
    purpose: ActivityPurpose
    direction: Literal["sent", "received"]
    # A transfer or settlement: what moved. A shared expense: the contact's share of it.
    amount: Decimal
    description: str | None


class ActivityPage(BaseModel):
    total: int
    items: list[ActivityRead]


class ContactSummary(BaseModel):
    contact_id: UUID
    # The ledger is the authority: receivable and payable are the balances of "Due from" and "Due to".
    total_receivable: Decimal
    total_payable: Decimal
    net_balance: Decimal
    # Over everything ever done with the contact.
    total_lent: Decimal
    total_borrowed: Decimal
    total_expenses_shared: Decimal
    total_settlements: Decimal
    open_obligations: int
    recent: list[ActivityRead]
