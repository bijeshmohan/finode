from datetime import date as Date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..models.transaction import PostingSide


FrequencyName = Literal["daily", "weekly", "monthly", "yearly"]


class RecurringPostingData(BaseModel):
    """One row of a split rule, like a transaction's posting: `value` is what it is worth in the rule's
    currency (only needed when the account holds something else)."""

    account: UUID
    side: PostingSide
    amount: Decimal = Field(gt=0, decimal_places=8, max_digits=24)
    value: Decimal | None = Field(default=None, gt=0, decimal_places=8, max_digits=24)


class RecurringBase(BaseModel):
    # A simple rule: `amount` leaves `from_account` and `received_amount` arrives in `to_account`
    # (only when the two accounts hold different things) ...
    from_account: UUID | None = None
    to_account: UUID | None = None
    amount: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    received_amount: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
    # ... or a split across several accounts instead, balancing in `currency` (the default currency when left out).
    postings: list[RecurringPostingData] = []
    currency: str | None = Field(default=None, max_length=12)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)
    frequency: FrequencyName = "monthly"
    every: int = Field(default=1, ge=1, le=366)
    start_date: Date = Field(default_factory=Date.today)
    end_date: Date | None = None

    @field_validator("amount", "received_amount")
    @classmethod
    def must_be_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("amount must be positive!")
        return v

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
        simple = (self.from_account, self.to_account, self.amount, self.received_amount)
        if self.postings:
            if len(self.postings) < 2:
                raise ValueError("a split needs at least two postings!")
            if any(v is not None for v in simple):
                raise ValueError("give either from, to and amount, or postings, not both!")
        elif None in (self.from_account, self.to_account, self.amount):
            raise ValueError("a recurring transaction needs from, to and an amount, or postings!")
        else:
            self.currency = None  # a simple rule works out its currency itself
        return self


class RecurringCreate(RecurringInput):
    pass


class RecurringUpdate(RecurringInput):
    pass


class RecurringRead(RecurringBase):
    rid: UUID
    next_date: Date
    last_date: Date | None = None
    active: bool
    last_error: str | None = None
    created: datetime
    updated: datetime
