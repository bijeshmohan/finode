from datetime import date as Date
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import field_validator
from sqlmodel import Field

from .utils import TimestampMixin


class PostingSide(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class Transaction(TimestampMixin, table=True):
    __tablename__ = "transactions"

    tid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    date: Date = Field(default_factory=Date.today)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)


class Posting(TimestampMixin, table=True):
    __tablename__ = "postings"

    pid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    transaction: UUID = Field(index=True, foreign_key="transactions.tid")
    account: UUID = Field(index=True, foreign_key="accounts.aid")
    side: PostingSide
    amount: Decimal = Field(decimal_places=2, max_digits=12)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v
