from datetime import date as Date
from decimal import Decimal
from enum import Enum
from uuid import UUID, uuid4

from pydantic import field_validator
from sqlalchemy import CheckConstraint, Index
from sqlmodel import Field

from .utils import Amount, TimestampMixin


class PostingSide(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class Transaction(TimestampMixin, table=True):
    __tablename__ = "transactions"
    # A recurring rule records each of its occurrences once, even if two workers race to do it.
    __table_args__ = (Index("uq_transactions_recurring", "recurring_id", "recurring_date", unique=True),)

    tid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    date: Date = Field(default_factory=Date.today)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)
    # The currency the transaction balances in: the postings' `value` is expressed in it.
    currency_id: UUID = Field(foreign_key="commodities.cid")
    # Where the transaction was entered and last changed: "web", "api", "import", or
    # "mcp:<token name>" for an AI assistant. None for entries made before this was recorded.
    created_via: str | None = Field(default=None, max_length=60)
    updated_via: str | None = Field(default=None, max_length=60)
    # Set when a recurring rule recorded it: the rule and the occurrence it stands for.
    recurring_id: UUID | None = Field(default=None, foreign_key="recurring_transactions.rid", index=True)
    recurring_date: Date | None = Field(default=None)


class Posting(TimestampMixin, table=True):
    __tablename__ = "postings"
    # The ledger's own rules, enforced by the database as well as the service.
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_postings_amount_positive"),
        CheckConstraint("value > 0", name="ck_postings_value_positive"),
        CheckConstraint("side IN ('DEBIT', 'CREDIT')", name="ck_postings_side"),
    )

    pid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    transaction: UUID = Field(index=True, foreign_key="transactions.tid")
    account: UUID = Field(index=True, foreign_key="accounts.aid")
    side: PostingSide
    # Quantity of the account's commodity.
    amount: Decimal = Field(sa_type=Amount())
    # The same posting measured in the transaction's currency; debits and credits balance on this.
    value: Decimal = Field(sa_type=Amount())

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v
