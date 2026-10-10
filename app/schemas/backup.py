"""The full-backup file: everything a user has recorded, in one JSON document (see services/backup.py)."""

from datetime import date as Date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from ..models.transaction import PostingSide


FORMAT = "finode-backup"
VERSION = 1


class BackupProfile(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    default_currency: str
    max_depth_assets: int = 0
    max_depth_liabilities: int = 0
    max_depth_equity: int = 0
    max_depth_income: int = 0
    max_depth_expenses: int = 0


class BackupCommodity(BaseModel):
    """One of the user's own assets (built-in currencies are not part of a backup)."""

    code: str
    name: str
    kind: str
    decimals: int = 2
    symbol: str | None = None


class BackupPrice(BaseModel):
    commodity: str
    quote: str
    date: Date
    price: Decimal


class BackupAccount(BaseModel):
    id: UUID
    parent_id: UUID | None = None
    name: str
    details: str | None = None
    commodity: str | None = None
    on_budget: bool = False
    closed_on: Date | None = None
    payment_category_id: UUID | None = None


class BackupPosting(BaseModel):
    account: UUID
    side: PostingSide
    amount: Decimal
    value: Decimal


class BackupTransaction(BaseModel):
    id: UUID
    date: Date
    payee: str | None = None
    comment: str | None = None
    currency: str
    created_via: str | None = None
    updated_via: str | None = None
    recurring_id: UUID | None = None
    recurring_date: Date | None = None
    postings: list[BackupPosting]


class BackupRecurringPosting(BaseModel):
    account: UUID
    side: PostingSide
    amount: Decimal
    value: Decimal | None = None


class BackupRecurring(BaseModel):
    id: UUID
    from_account: UUID | None = None
    to_account: UUID | None = None
    amount: Decimal | None = None
    received_amount: Decimal | None = None
    currency: str | None = None
    postings: list[BackupRecurringPosting] = []
    payee: str | None = None
    comment: str | None = None
    frequency: str
    every: int = 1
    start_date: Date
    end_date: Date | None = None
    next_date: Date
    last_date: Date | None = None
    active: bool = True
    last_error: str | None = None


class BackupAllocation(BaseModel):
    month: Date
    account_id: UUID
    amount: Decimal


class BackupTarget(BaseModel):
    account_id: UUID
    kind: str
    amount: Decimal
    target_date: Date | None = None


class BackupFile(BaseModel):
    format: str
    version: int
    exported_at: datetime | None = None
    profile: BackupProfile
    commodities: list[BackupCommodity] = []
    prices: list[BackupPrice] = []
    accounts: list[BackupAccount]
    transactions: list[BackupTransaction] = []
    recurring: list[BackupRecurring] = []
    allocations: list[BackupAllocation] = []
    targets: list[BackupTarget] = []


class RestoreSummary(BaseModel):
    """What a restore will do (or did); errors mean nothing is saved."""

    errors: list[str] = Field(default_factory=list)
    accounts: int = 0
    transactions: int = 0
    recurring: int = 0
    allocations: int = 0
    targets: int = 0
    prices: int = 0
    commodities: list[str] = Field(default_factory=list)
    date_from: Date | None = None
    date_to: Date | None = None
