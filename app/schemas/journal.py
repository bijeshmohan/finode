from datetime import date as Date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..models.journal import JournalSide


class JournalLineBase(BaseModel):
    account: UUID
    side: JournalSide
    amount: Decimal = Field(decimal_places=2, max_digits=12)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive!")
        return v


class JournalLineCreate(JournalLineBase):
    ...


class JournalLineRead(JournalLineBase):
    lid: UUID
    entry: UUID
    created: datetime
    updated: datetime


class JournalEntryBase(BaseModel):
    date: Date = Field(default_factory=Date.today)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)


class JournalEntryCreate(JournalEntryBase):
    lines: list[JournalLineCreate]

    @model_validator(mode="after")
    def lines_must_balance(self) -> "JournalEntryCreate":
        validate_balanced_lines(self.lines)
        return self


class JournalEntryRead(JournalEntryBase):
    jid: UUID
    lines: list[JournalLineRead]
    created: datetime
    updated: datetime


class JournalEntryUpdate(BaseModel):
    date: Date | None = Field(default=None)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)
    lines: list[JournalLineCreate] | None = Field(default=None)

    @model_validator(mode="after")
    def non_nullable_fields_must_not_be_null(self) -> "JournalEntryUpdate":
        if "date" in self.model_fields_set and self.date is None:
            raise ValueError("the field 'date' must not be null!")
        return self

    @model_validator(mode="after")
    def lines_must_balance(self) -> "JournalEntryUpdate":
        if self.lines is not None:
            validate_balanced_lines(self.lines)
        return self


def validate_balanced_lines(lines: list[JournalLineCreate]) -> None:
    if len(lines) < 2:
        raise ValueError("journal entries must contain at least two lines!")

    debit_total = sum(
        line.amount for line in lines if line.side == JournalSide.DEBIT
    )
    credit_total = sum(
        line.amount for line in lines if line.side == JournalSide.CREDIT
    )
    if debit_total != credit_total:
        raise ValueError("journal entry debits and credits must balance!")
