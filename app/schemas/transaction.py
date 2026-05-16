from datetime import date as Date
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class Type(Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class TransactionBase(BaseModel):
    amount: Decimal = Field(decimal_places=2, max_digits=12)
    category: UUID | None = Field(default=None)
    date: Date = Field(default_factory=Date.today)
    source: UUID | None = Field(default=None)
    destination: UUID | None = Field(default=None)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)

    @field_validator("amount")
    @classmethod
    def amount_must_not_be_zero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("amount must not be zero!")
        return v

    @model_validator(mode="after")
    def either_source_or_destination_must_be_provided(self) -> "TransactionBase":
        if self.source is None and self.destination is None:
            raise ValueError("either 'source' or 'destination' must be provided!")
        return self


class TransactionCreate(TransactionBase):
    ...


class TransactionRead(TransactionBase):
    tid: UUID


class TransactionUpdate(BaseModel):
    amount: Decimal | None = Field(
        default=None,
        decimal_places=2,
        max_digits=12
    )
    category: UUID | None = Field(default=None)
    date: Date | None = Field(default=None)
    source: UUID | None = Field(default=None)
    destination: UUID | None = Field(default=None)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)

    @field_validator("amount")
    @classmethod
    def amount_must_not_be_zero(cls, v: Decimal | None) -> Decimal | None:
        if v == 0:
            raise ValueError("amount must not be zero!")
        return v
