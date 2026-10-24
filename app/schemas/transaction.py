from datetime import date as Date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..models.transaction import PostingSide
from ..clock import local_today
from .day import Day


class PostingBase(BaseModel):
    account: UUID
    side: PostingSide
    # How many decimals it may have is checked against the currency.
    amount: Decimal = Field(decimal_places=8, max_digits=24)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive!")
        return v


class PostingCreate(PostingBase):
    ...


class PostingRead(PostingBase):
    pid: UUID
    transaction: UUID
    created: datetime
    updated: datetime


def _tidy_payee(value: str | None) -> str | None:
    """One line, single spaces, nothing at all when blank: a payee is a label, not text."""
    return " ".join(value.split()) or None if value is not None else None


def _tidy_comment(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


class TransactionBase(BaseModel):
    date: Day = Field(default_factory=local_today)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)

    _tidy_payee = field_validator("payee")(lambda cls, v: _tidy_payee(v))
    _tidy_comment = field_validator("comment")(lambda cls, v: _tidy_comment(v))


class TransactionCreate(TransactionBase):
    postings: list[PostingCreate]
    # An earlier entry of the person's own that this one is related to.
    related_id: UUID | None = None

    @model_validator(mode="after")
    def postings_must_balance(self) -> "TransactionCreate":
        validate_balanced_postings(self.postings)
        return self


class TransactionRead(TransactionBase):
    tid: UUID
    # Where it was entered and last changed: "web", "api", "import" or "mcp:<token name>"; None if unknown.
    created_via: str | None = None
    updated_via: str | None = None
    # The recurring rule that recorded it, if one did and still exists.
    recurring_id: UUID | None = None
    # The entry this one is related to, if it still exists.
    related_id: UUID | None = None
    postings: list[PostingRead]
    created: datetime
    updated: datetime


class TransactionUpdate(BaseModel):
    date: Day | None = Field(default=None)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)
    postings: list[PostingCreate] | None = Field(default=None)
    # Send null to remove the link; leave it out to keep it.
    related_id: UUID | None = None

    _tidy_payee = field_validator("payee")(lambda cls, v: _tidy_payee(v))
    _tidy_comment = field_validator("comment")(lambda cls, v: _tidy_comment(v))

    @model_validator(mode="after")
    def non_nullable_fields_must_not_be_null(self) -> "TransactionUpdate":
        if "date" in self.model_fields_set and self.date is None:
            raise ValueError("the field 'date' must not be null!")
        return self

    @model_validator(mode="after")
    def postings_must_balance(self) -> "TransactionUpdate":
        if self.postings is not None:
            validate_balanced_postings(self.postings)
        return self


def validate_balanced_postings(postings: list[PostingCreate]) -> None:
    if len(postings) < 2:
        raise ValueError("transactions must contain at least two postings!")

    debit_total = sum(
        posting.amount for posting in postings if posting.side == PostingSide.DEBIT
    )
    credit_total = sum(
        posting.amount for posting in postings if posting.side == PostingSide.CREDIT
    )
    if debit_total != credit_total:
        raise ValueError("transaction debits and credits must balance!")


class HistoryPosting(BaseModel):
    # Account path, e.g. "Expenses:Food:Groceries".
    account: str
    side: PostingSide
    amount: Decimal


class HistoryRead(BaseModel):
    """The transaction as it stood after one change (as it stood when deleted, for a deletion)."""

    hid: UUID
    transaction: UUID
    action: Literal["created", "updated", "deleted"]
    at: datetime
    # "web", "api", "import", "recurring" or "mcp:<token name>"; None if unknown.
    via: str | None = None
    date: Date
    payee: str | None = None
    comment: str | None = None
    postings: list[HistoryPosting]
