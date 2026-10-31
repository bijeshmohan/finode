from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..clock import local_today
from ..models.transaction import PostingSide
from ..tags import clean_names
from .day import Day


class _PostingFields(BaseModel):
    side: PostingSide
    # How many decimals it may have is checked against the currency.
    amount: Decimal = Field(decimal_places=8, max_digits=24)
    # What the line was for (a budget category). Leave it out and a payment into a loan or fund that has a payment
    # category takes that one, and a line on Expenses or Income with none is Uncategorised.
    category_id: UUID | None = None

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive!")
        return v


class PostingBase(_PostingFields):
    account_id: UUID

    @property
    def target(self) -> UUID:
        return self.account_id


class PostingCreate(_PostingFields):
    # Leave it out and name the category: the line posts to Expenses (a spending category) or Income (an earning one).
    account_id: UUID | None = None

    @model_validator(mode="after")
    def _names_an_account_or_a_category(self) -> PostingCreate:
        if self.account_id is None and self.category_id is None:
            raise ValueError("a line names an account or a category!")
        return self

    @property
    def target(self) -> UUID:
        """The account the line posts to (always set once the entry has been checked)."""
        if self.account_id is None:
            raise ValueError("the line has no account yet!")
        return self.account_id


class PostingRead(PostingBase):
    id: UUID
    transaction_id: UUID
    created: datetime
    updated: datetime


def _tidy_payee(value: str | None) -> str | None:
    """One line, single spaces, nothing at all when blank: a payee is a label, not text."""
    return " ".join(value.split()) or None if value is not None else None


def _tidy_comment(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


def _tidy_source(value: str | None) -> str | None:
    return (value.strip().lower() or None) if value is not None else None


def _tidy_reference(value: str | None) -> str | None:
    return (value.strip() or None) if value is not None else None


def _tidy_url(value: str | None) -> str | None:
    value = _tidy_reference(value)
    if value is not None and not value.lower().startswith(("http://", "https://")):
        raise ValueError("source_url must be a web address starting with http:// or https://!")
    return value


class ReferenceFields(BaseModel):
    """Where an entry came from outside finode: a short kind, the reference that source gave it and a link back.
    A person's (source, external_id) is used once, so recording it again finds the entry."""

    source: str | None = Field(default=None, max_length=40)
    external_id: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=500)

    @field_validator("source")
    @classmethod
    def _clean_source(cls, value: str | None) -> str | None:
        return _tidy_source(value)

    @field_validator("external_id")
    @classmethod
    def _clean_external_id(cls, value: str | None) -> str | None:
        return _tidy_reference(value)

    @field_validator("source_url")
    @classmethod
    def _clean_source_url(cls, value: str | None) -> str | None:
        return _tidy_url(value)


class TransactionBase(BaseModel):
    date: Day = Field(default_factory=local_today)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)

    @field_validator("payee")
    @classmethod
    def _clean_payee(cls, value: str | None) -> str | None:
        return _tidy_payee(value)

    @field_validator("comment")
    @classmethod
    def _clean_comment(cls, value: str | None) -> str | None:
        return _tidy_comment(value)


class TransactionCreate(TransactionBase, ReferenceFields):
    postings: list[PostingCreate]
    # An earlier entry of the person's own that this one is related to.
    related_id: UUID | None = None
    # Labels on the entry ("goa-trip"): each in its one form (no #, lower case), once, at most 10.
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        return clean_names(value)

    @model_validator(mode="after")
    def reference_needs_a_source(self) -> TransactionCreate:
        if self.external_id and not self.source:
            raise ValueError("a reference (external_id) needs a source, for example 'gmail' or 'upi'!")
        return self

    @model_validator(mode="after")
    def postings_must_balance(self) -> TransactionCreate:
        validate_balanced_postings(self.postings)
        return self


class TransactionRead(TransactionBase, ReferenceFields):
    id: UUID
    # Where it was entered and last changed: "web", "api", "import" or "mcp:<token name>"; None if unknown.
    created_via: str | None = None
    updated_via: str | None = None
    # The recurring rule that recorded it, if one did and still exists.
    recurring_id: UUID | None = None
    # The entry this one is related to, if it still exists.
    related_id: UUID | None = None
    # The tags on the entry, A to Z.
    tags: list[str] = Field(default_factory=list)
    postings: list[PostingRead]
    created: datetime
    updated: datetime


class TransactionPreview(ReferenceFields):
    """What a dry run says would happen: the entry as it would be saved (nothing was saved)."""

    dry_run: Literal[True] = True
    # The entry being changed or deleted; None for one that would be made.
    id: UUID | None = None
    date: Day
    payee: str | None = None
    comment: str | None = None
    related_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)
    postings: list[PostingCreate]
    # Recording it would not make a new entry: this one already has the reference, with the same date and rows.
    already_recorded: UUID | None = None


# How many entries one batch may hold.
MAX_BATCH = 50


class TransactionBatch(BaseModel):
    transactions: list[TransactionCreate] = Field(min_length=1, max_length=MAX_BATCH)


class BatchEntryResult(BaseModel):
    # Which entry of the batch this is (1 is the first).
    item: int
    status: Literal["recorded", "already_recorded", "would_record"]
    transaction: TransactionRead | TransactionPreview


class BatchResult(BaseModel):
    dry_run: bool
    # False for a dry run (nothing was saved).
    saved: bool
    created: int
    already_recorded: int
    entries: list[BatchEntryResult]


class TransactionUpdate(ReferenceFields):
    date: Day | None = Field(default=None)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)
    postings: list[PostingCreate] | None = Field(default=None)
    # Send null to remove the link; leave it out to keep it.
    related_id: UUID | None = None
    # The entry's tags, all of them (replacing the old ones; [] takes them all off); leave it out to keep them.
    tags: list[str] | None = None

    @field_validator("payee")
    @classmethod
    def _clean_payee(cls, value: str | None) -> str | None:
        return _tidy_payee(value)

    @field_validator("comment")
    @classmethod
    def _clean_comment(cls, value: str | None) -> str | None:
        return _tidy_comment(value)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else clean_names(value)

    @model_validator(mode="after")
    def non_nullable_fields_must_not_be_null(self) -> TransactionUpdate:
        if "date" in self.model_fields_set and self.date is None:
            raise ValueError("the field 'date' must not be null!")
        return self

    @model_validator(mode="after")
    def postings_must_balance(self) -> TransactionUpdate:
        if self.postings is not None:
            validate_balanced_postings(self.postings)
        return self


def validate_balanced_postings(postings: list[PostingCreate]) -> None:
    if len(postings) < 2:
        raise ValueError("transactions must contain at least two postings!")

    debit_total = sum(posting.amount for posting in postings if posting.side == PostingSide.DEBIT)
    credit_total = sum(posting.amount for posting in postings if posting.side == PostingSide.CREDIT)
    if debit_total != credit_total:
        raise ValueError("transaction debits and credits must balance!")


class HistoryPosting(BaseModel):
    # Account path, e.g. "Expenses:Food:Groceries".
    account: str
    side: PostingSide
    amount: Decimal
    # The name of the category the line was for, when it had one.
    category: str | None = None


class HistoryRead(BaseModel):
    """The transaction as it stood after one change (as it stood when deleted, for a deletion)."""

    id: UUID
    transaction_id: UUID
    action: Literal["created", "updated", "deleted"]
    at: datetime
    # "web", "api", "import", "recurring" or "mcp:<token name>"; None if unknown.
    via: str | None = None
    date: Date
    payee: str | None = None
    comment: str | None = None
    source: str | None = None
    external_id: str | None = None
    source_url: str | None = None
    postings: list[HistoryPosting]


class ChangeRead(BaseModel):
    """One step in an entry's life, with what it changed compared with the step before."""

    id: UUID
    transaction_id: UUID
    action: Literal["created", "updated", "deleted"]
    at: datetime
    # "web", "api", "import", "recurring" or "mcp:<token name>"; None if unknown.
    via: str | None = None
    # The entry as it stood after this step.
    entry: HistoryRead
    # For an update: {field: {"from", "to"}} for date, payee, note and reference, and "postings" with the rows
    # "added", "removed" and "changed" (amount from/to). Empty for a creation or a deletion.
    changes: dict[str, Any] = Field(default_factory=dict)


class TagRead(BaseModel):
    """A tag: how many entries carry it and the day of the latest."""

    tag: str
    uses: int
    last_used: Date


class RouteAccount(BaseModel):
    id: UUID
    path: str


class PayeeRouteRead(BaseModel):
    from_account: RouteAccount
    to_account: RouteAccount
    uses: int


class PayeeDefaultRead(BaseModel):
    """How a payee is usually booked: the accounts of the newest simple entry, and the other routes seen."""

    payee: str
    uses: int
    # The payee was typed in full (capitals aside), not just a part of it.
    exact: bool
    kind: Literal["expense", "income", "transfer"]
    from_account: RouteAccount
    to_account: RouteAccount
    other_routes: list[PayeeRouteRead] = Field(default_factory=list)


class PayeeRead(BaseModel):
    payee: str
    count: int
