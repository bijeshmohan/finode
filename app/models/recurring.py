from datetime import date as Date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint
from sqlmodel import Field

from .utils import Amount, TimestampMixin


class Frequency:
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"

    ALL = (DAILY, WEEKLY, MONTHLY, YEARLY)


class RecurringTransaction(TimestampMixin, table=True):
    """A rule that records the same money movement every so often (rent, salary, a subscription).

    It is the "simple" form of a transaction: `amount` leaves `from_account` and arrives in
    `to_account` (`received_amount` when the two hold different things).
    """

    __tablename__ = "recurring_transactions"
    __table_args__ = (
        CheckConstraint("frequency IN ('daily', 'weekly', 'monthly', 'yearly')", name="ck_recurring_frequency"),
        CheckConstraint("every >= 1", name="ck_recurring_every"),
    )

    rid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    from_account: UUID = Field(foreign_key="accounts.aid")
    to_account: UUID = Field(foreign_key="accounts.aid")
    amount: Decimal = Field(sa_type=Amount())
    received_amount: Decimal | None = Field(default=None, sa_type=Amount())
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)
    frequency: str = Field(max_length=10)
    # "Every 2 weeks": the number of days, weeks, months or years between occurrences.
    every: int = Field(default=1)
    # Occurrences are start_date, then every `every` units after it (a monthly rule on the 31st
    # falls on the last day of shorter months).
    start_date: Date
    end_date: Date | None = Field(default=None)
    # The next occurrence that has not been recorded yet, and the last one that was.
    next_date: Date
    last_date: Date | None = Field(default=None)
    active: bool = Field(default=True)
    # Why the latest attempt to record it failed (an account that can no longer be posted to, say).
    last_error: str | None = Field(default=None, max_length=300)
