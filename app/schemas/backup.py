"""The full-backup file: everything a user has recorded, in one JSON document (see services/backup.py)."""

from datetime import date as Date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from ..models.transaction import PostingSide
from .day import Day


FORMAT = "finode-backup"
VERSION = 2
# Files of version 1 (before finode kept one currency) are still read; what they carry beyond that is below.
READS = (1, 2)


class BackupProfile(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    default_currency: str
    # Files written before accounts were fixed at two levels carry depth limits; they are ignored.
    max_depth_assets: int = Field(default=0, exclude=True)
    max_depth_liabilities: int = Field(default=0, exclude=True)
    max_depth_equity: int = Field(default=0, exclude=True)
    max_depth_income: int = Field(default=0, exclude=True)
    max_depth_expenses: int = Field(default=0, exclude=True)
    locked_through: Day | None = None
    advanced: bool = False


class BackupAccount(BaseModel):
    id: UUID
    parent_id: UUID | None = None
    name: str
    details: str | None = None
    # Version 1 only: what the account held. Read to check it is the profile's currency, never written.
    commodity: str | None = Field(default=None, exclude=True)
    on_budget: bool = False
    closed_on: Day | None = None
    payment_category_id: UUID | None = None
    # Older backups: accounts could be pinned. Read, never written.
    pinned: bool = Field(default=False, exclude=True)
    position: int | None = None
    # Set on the built-in groups (Bank Accounts, Cash, Investments, Credit Cards, Loans); a restore maps them onto the person's own.
    system_key: str | None = None


class BackupPosting(BaseModel):
    account: UUID
    side: PostingSide
    amount: Decimal
    # Version 1 only: the worth in the transaction's currency; must equal the amount.
    value: Decimal | None = Field(default=None, exclude=True)


class BackupTransaction(BaseModel):
    id: UUID
    date: Day
    payee: str | None = None
    comment: str | None = None
    # Version 1 only: the transaction's currency; must be the profile's.
    currency: str | None = Field(default=None, exclude=True)
    created_via: str | None = None
    updated_via: str | None = None
    recurring_id: UUID | None = None
    recurring_date: Day | None = None
    postings: list[BackupPosting]


class BackupRecurringPosting(BaseModel):
    account: UUID
    side: PostingSide
    amount: Decimal
    value: Decimal | None = Field(default=None, exclude=True)


class BackupRecurring(BaseModel):
    id: UUID
    from_account: UUID | None = None
    to_account: UUID | None = None
    amount: Decimal | None = None
    received_amount: Decimal | None = Field(default=None, exclude=True)
    currency: str | None = Field(default=None, exclude=True)
    postings: list[BackupRecurringPosting] = []
    payee: str | None = None
    comment: str | None = None
    frequency: str
    every: int = 1
    start_date: Day
    end_date: Day | None = None
    next_date: Day
    last_date: Day | None = None
    skipped_date: Day | None = None
    active: bool = True
    last_error: str | None = None


class BackupAllocation(BaseModel):
    month: Day
    account_id: UUID
    amount: Decimal


class BackupTarget(BaseModel):
    account_id: UUID
    kind: str
    amount: Decimal
    target_date: Day | None = None
    weekday: int | None = None


class BackupGoalMonth(BaseModel):
    month: Day
    amount: Decimal


class BackupGoal(BaseModel):
    name: str
    amount: Decimal
    target_date: Day
    # What was set aside for it, month by month.
    allocations: list[BackupGoalMonth] = []


class BackupFile(BaseModel):
    format: str
    version: int
    exported_at: datetime | None = None
    profile: BackupProfile
    # Version 1 only: own assets and prices, which finode no longer keeps (a file that has any is refused).
    commodities: list[dict] = Field(default=[], exclude=True)
    prices: list[dict] = Field(default=[], exclude=True)
    accounts: list[BackupAccount]
    transactions: list[BackupTransaction] = []
    recurring: list[BackupRecurring] = []
    allocations: list[BackupAllocation] = []
    targets: list[BackupTarget] = []
    # Goals (their own records since the goals table; a file from before has its goals as categories with a target).
    goals: list[BackupGoal] = []


class RestoreSummary(BaseModel):
    """What a restore will do (or did); errors mean nothing is saved."""

    errors: list[str] = Field(default_factory=list)
    accounts: int = 0
    transactions: int = 0
    recurring: int = 0
    allocations: int = 0
    targets: int = 0
    goals: int = 0
    date_from: Date | None = None
    date_to: Date | None = None
