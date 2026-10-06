from datetime import date as Date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


FrequencyName = Literal["daily", "weekly", "monthly", "yearly"]


class RecurringBase(BaseModel):
    from_account: UUID
    to_account: UUID
    # How much leaves `from_account`; `received_amount` is how much arrives in `to_account`
    # (only when the two accounts hold different things).
    amount: Decimal = Field(decimal_places=8, max_digits=24)
    received_amount: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)
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


class RecurringCreate(RecurringBase):
    pass


class RecurringUpdate(RecurringBase):
    pass


class RecurringRead(RecurringBase):
    rid: UUID
    next_date: Date
    last_date: Date | None = None
    active: bool
    last_error: str | None = None
    created: datetime
    updated: datetime
