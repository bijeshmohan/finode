from datetime import date as Date, datetime
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
    def source_and_destination_must_not_be_same(self) -> "TransactionBase":
        if (self.source is not None and self.destination is not None) and self.source == self.destination:
            raise ValueError("both 'source' and 'destination' must not be the same!")
        return self


class TransactionCreate(TransactionBase):
    ...


class TransactionRead(TransactionBase):
    tid: UUID
    created: datetime
    updated: datetime


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

    @model_validator(mode="after")
    def non_nullable_fields_must_not_be_null(self) -> "TransactionUpdate":
        for field in ("amount", "date"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"the field '{field}' must not be null!")
        return self

    @model_validator(mode="after")
    def source_and_destination_must_not_be_same(self) -> "TransactionUpdate":
        if (self.source is not None and self.destination is not None) and self.source == self.destination:
            raise ValueError("both 'source' and 'destination' must not be the same!")
        return self
