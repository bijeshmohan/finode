from datetime import date as Date
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import field_validator
from sqlmodel import Field

from .utils import TimestampMixin


class JournalSide(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class JournalEntry(TimestampMixin, table=True):
    __tablename__ = "journal_entries"

    jid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    date: Date = Field(default_factory=Date.today)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)


class JournalLine(TimestampMixin, table=True):
    __tablename__ = "journal_lines"

    lid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    entry: UUID = Field(index=True, foreign_key="journal_entries.jid")
    account: UUID = Field(index=True, foreign_key="accounts.aid")
    side: JournalSide
    amount: Decimal = Field(decimal_places=2, max_digits=12)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v
