"""The full-backup file: everything a user has recorded, in one JSON document (see services/backup.py)."""

from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

from ..models.transaction import PostingSide
from .day import Day

FORMAT = "finode-backup"
VERSION = 5
# Files of version 1 (before finode kept one currency) are still read; what they carry beyond that is below.
# Before version 5 a category was an Income or Expenses account: a restore turns those accounts into categories.
READS = (1, 2, 3, 4, 5)


class BackupProfile(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    default_currency: str


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
    # Set on the built-in groups (Bank Accounts, Cash, Investments, Credit Cards, Loans); a restore maps them onto the person's own.
    system_key: str | None = None
    # Version 4 only: the built-in key of the category this Income or Expenses account stood for.
    category_key: str | None = Field(default=None, exclude=True)


class BackupCategory(BaseModel):
    """Version 5: what money was for (Groceries, EMI, Salary). A group has no parent; the categories in it name it."""

    id: UUID
    name: str
    kind: str
    parent_id: UUID | None = None
    details: str | None = None
    closed_on: Day | None = None
    # "uncategorised.spending" / "uncategorised.earning" on the built-in ones.
    system_key: str | None = None


class BackupPosting(BaseModel):
    account: UUID
    side: PostingSide
    amount: Decimal
    # What the line was for: a category of the file. Before version 5 this was the id of an Income or Expenses
    # account (the same id the category got), and a line to one of those had none: a restore sorts it out.
    category: UUID | None = None
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
    related_id: UUID | None = None
    # The entry's tags. A file before version 3 has none: its notes carry #words, which a restore turns into tags.
    tags: list[str] = Field(default_factory=list)
    source: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    postings: list[BackupPosting]


class BackupRecurringPosting(BaseModel):
    account: UUID
    side: PostingSide
    amount: Decimal
    category: UUID | None = None
    value: Decimal | None = Field(default=None, exclude=True)


class BackupRecurring(BaseModel):
    id: UUID
    from_account: UUID | None = None
    to_account: UUID | None = None
    amount: Decimal | None = None
    category: UUID | None = None
    received_amount: Decimal | None = Field(default=None, exclude=True)
    currency: str | None = Field(default=None, exclude=True)
    postings: list[BackupRecurringPosting] = []
    payee: str | None = None
    comment: str | None = None
    # The tags every entry the rule records gets (a file from before has none).
    tags: list[str] = []
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
    # The category the money was assigned to (called `account_id` before version 5).
    category_id: UUID = Field(validation_alias=AliasChoices("category_id", "account_id"))
    amount: Decimal


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
    categories: list[BackupCategory] = []
    transactions: list[BackupTransaction] = []
    recurring: list[BackupRecurring] = []
    allocations: list[BackupAllocation] = []
    # Goals (their own records since the goals table; a file from before has its goals as plain categories).
    goals: list[BackupGoal] = []


class RestoreSummary(BaseModel):
    """What a restore will do (or did); errors mean nothing is saved."""

    errors: list[str] = Field(default_factory=list)
    accounts: int = 0
    categories: int = 0
    transactions: int = 0
    recurring: int = 0
    allocations: int = 0
    goals: int = 0
    tags: int = 0
    date_from: Date | None = None
    date_to: Date | None = None
