from datetime import date as Date
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..clock import local_today
from ..models.transaction import PostingSide
from ..tags import clean_names
from .day import Day

FrequencyName = Literal["daily", "weekly", "monthly", "yearly"]


class RecurringPostingData(BaseModel):
    """One row of a split rule, like a transaction's posting."""

    account: UUID
    side: PostingSide
    amount: Decimal = Field(gt=Decimal(0), decimal_places=8, max_digits=24)


class RecurringBase(BaseModel):
    # A simple rule: `amount` leaves `from_account` and arrives in `to_account` ...
    from_account: UUID | None = None
    to_account: UUID | None = None
    amount: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    # ... or a split across several accounts instead.
    postings: list[RecurringPostingData] = []
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)
    # Labels every entry the rule records gets ("rent"): each in its one form (no #, lower case), once, at most 10.
    tags: list[str] = Field(default_factory=list)
    frequency: FrequencyName = "monthly"
    every: int = Field(default=1, ge=1, le=366)
    start_date: Day = Field(default_factory=local_today)
    end_date: Day | None = None

    @field_validator("amount")
    @classmethod
    def must_be_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("amount must be positive!")
        return v

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: list[str]) -> list[str]:
        return clean_names(value)

    @field_validator("payee", "comment")
    @classmethod
    def blank_is_none(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @model_validator(mode="after")
    def ends_after_it_starts(self):
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("the end date cannot be before the start date!")
        return self


class RecurringInput(RecurringBase):
    """What a client sends: a simple rule or a split, never both and never neither."""

    @model_validator(mode="after")
    def simple_or_split(self):
        simple = (self.from_account, self.to_account, self.amount)
        if self.postings:
            if len(self.postings) < 2:
                raise ValueError("a split needs at least two postings!")
            if any(v is not None for v in simple):
                raise ValueError("give either from, to and amount, or postings, not both!")
        elif None in (self.from_account, self.to_account, self.amount):
            raise ValueError("a recurring transaction needs from, to and an amount, or postings!")
        return self


class RecurringCreate(RecurringInput):
    pass


class RecurringUpdate(RecurringInput):
    pass


class RecurringRead(RecurringBase):
    rid: UUID
    next_date: Date
    last_date: Date | None = None
    # The occurrence skipped most recently (nothing was recorded for it).
    skipped_date: Date | None = None
    active: bool
    last_error: str | None = None
    created: datetime
    updated: datetime
