"""The accounts table: a tree of the places money is kept or owed, under five roots per person."""

from datetime import date as Date
from uuid import UUID, uuid4

from pydantic import field_validator
from sqlalchemy import CheckConstraint, Index, false, text
from sqlmodel import Field

from .utils import TimestampMixin


class Account(TimestampMixin, table=True):
    __tablename__ = "accounts"
    __table_args__ = (
        Index(
            "uq_accounts_user_root_name",
            "user_id",
            "name",
            unique=True,
            sqlite_where=text("parent_id IS NULL"),
            postgresql_where=text("parent_id IS NULL"),
        ),
        # One built-in group of each kind per person (see services/account.py FIXED_PARENTS).
        Index(
            "uq_accounts_user_system_key",
            "user_id",
            "system_key",
            unique=True,
            sqlite_where=text("system_key IS NOT NULL"),
            postgresql_where=text("system_key IS NOT NULL"),
        ),
        # A card's bill days (see services/cards.py): 1 to 31, both or neither.
        CheckConstraint("statement_day IS NULL OR statement_day BETWEEN 1 AND 31", name="ck_accounts_statement_day"),
        CheckConstraint("due_day IS NULL OR due_day BETWEEN 1 AND 31", name="ck_accounts_due_day"),
        CheckConstraint("(statement_day IS NULL) = (due_day IS NULL)", name="ck_accounts_bill_days_together"),
        CheckConstraint("bill_rounding IN ('none', 'nearest', 'up')", name="ck_accounts_bill_rounding"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = Field(default=None, foreign_key="accounts.id", nullable=True)
    # The day the account was closed: no longer offered or posted to, history kept (see AccountService.close).
    closed_on: Date | None = Field(default=None)
    # A Credit Card's day of the month the bank closes a bill and the day it must be paid by.
    statement_day: int | None = Field(default=None)
    due_day: int | None = Field(default=None)
    # How the bank rounds the bill: "none" (to the paisa), "nearest" or "up" (to a whole unit of the currency).
    bill_rounding: str = Field(default="none", max_length=8, sa_column_kwargs={"server_default": "none"})
    # Set on the four account types' own groups (services/account_types.py: assets.bank, assets.cash,
    # liabilities.cards, assets.wallet): they cannot be renamed, moved, closed or deleted, and every account under one is
    # part of the budget.
    system_key: str | None = Field(default=None, max_length=40)
    # Whether the person pinned this account: the Accounts page lists pinned ones again in a row at its top.
    pinned: bool = Field(default=False, sa_column_kwargs={"server_default": false()})

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        return v
