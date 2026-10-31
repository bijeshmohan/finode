from datetime import date as Date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import field_validator
from sqlalchemy import CheckConstraint, Index, text
from sqlmodel import Field

from ..clock import local_today
from .utils import Amount, TimestampMixin


class PostingSide(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class Transaction(TimestampMixin, table=True):
    __tablename__ = "transactions"
    # A recurring rule records each of its occurrences once, even if two workers race to do it.
    __table_args__ = (
        Index("uq_transactions_recurring", "recurring_id", "recurring_date", unique=True),
        Index(
            "uq_transactions_reference",
            "user_id",
            "source",
            "external_id",
            unique=True,
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    date: Date = Field(default_factory=local_today)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)
    # Where the transaction was entered and last changed: "web", "api", "import", or
    # "mcp:<token name>" for an AI assistant. None for entries made before this was recorded.
    created_via: str | None = Field(default=None, max_length=60)
    updated_via: str | None = Field(default=None, max_length=60)
    # Set when a recurring rule recorded it: the rule and the occurrence it stands for.
    recurring_id: UUID | None = Field(default=None, foreign_key="recurring_transactions.id", index=True)
    recurring_date: Date | None = Field(default=None)
    # The earlier entry this one belongs with (a refund, a reversal, a cash-back…): just a link, no meaning yet.
    related_id: UUID | None = Field(default=None, foreign_key="transactions.id", index=True)
    # Where the entry came from outside finode (a bank, a mail, a UPI app): a short kind ("gmail", "upi"), the
    # reference that source gave it and a link back. A source's reference is used once per person, so recording the
    # same one again finds the entry instead of making a copy.
    source: str | None = Field(default=None, max_length=40)
    external_id: str | None = Field(default=None, max_length=120)
    source_url: str | None = Field(default=None, max_length=500)


class Posting(TimestampMixin, table=True):
    __tablename__ = "postings"
    # The ledger's own rules, enforced by the database as well as the service.
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_postings_amount_positive"),
        CheckConstraint("side IN ('DEBIT', 'CREDIT')", name="ck_postings_side"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    transaction_id: UUID = Field(index=True, foreign_key="transactions.id")
    account_id: UUID = Field(index=True, foreign_key="accounts.id")
    side: PostingSide
    amount: Decimal = Field(sa_type=Amount())
    # What this line was for (a budget category). Any line may carry one; the budget counts it when the entry touches
    # a budget account and the line's own account is not part of the budget.
    category_id: UUID | None = Field(default=None, foreign_key="budget_categories.id", nullable=True, index=True)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive")
        return v
