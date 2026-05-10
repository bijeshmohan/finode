from datetime import date as Date
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Type(Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class TransactionBase(BaseModel):
    amount: Decimal = Field(decimal_places=2, max_digits=12)
    category: UUID
    date: Date = Field(default_factory=Date.today)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)

    @field_validator("amount")
    @classmethod
    def amount_must_not_be_zero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("amount must not be zero")
        return v


class ExpenseBase(TransactionBase):
    source: UUID


class ExpenseCreate(ExpenseBase):
    ...


class ExpenseRead(ExpenseBase):
    tid: UUID


class ExpenseUpdate(ExpenseBase):
    ...


class IncomeBase(TransactionBase):
    destination: UUID


class IncomeCreate(IncomeBase):
    ...


class IncomeRead(IncomeBase):
    tid: UUID


class IncomeUpdate(IncomeBase):
    ...


class TransferBase(TransactionBase):
    source: UUID
    destination: UUID


class TransferCreate(TransferBase):
    ...


class TransferRead(TransferBase):
    tid: UUID


class TransferUpdate(TransferBase):
    ...
