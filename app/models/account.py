from datetime import date as Date
from uuid import UUID, uuid4

from pydantic import field_validator
from sqlalchemy import Index, false, text
from sqlmodel import Field

from .utils import TimestampMixin


class Account(TimestampMixin, table=True):
    __tablename__ = "accounts"
    __table_args__ = (
        Index(
            "uq_accounts_user_root_name",
            "user",
            "name",
            unique=True,
            sqlite_where=text("parent_id IS NULL"),
            postgresql_where=text("parent_id IS NULL"),
        ),
        # One built-in group of each kind per person (see services/account.py FIXED_PARENTS).
        Index(
            "uq_accounts_user_system_key",
            "user",
            "system_key",
            unique=True,
            sqlite_where=text("system_key IS NOT NULL"),
            postgresql_where=text("system_key IS NOT NULL"),
        ),
    )

    aid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = Field(default=None, foreign_key="accounts.aid", nullable=True)
    # Whether this asset or liability account (a bank, a credit card) is part of the budget (see services/budget.py).
    on_budget: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    # The day the account was closed: no longer offered or posted to, history kept (see AccountService.close).
    closed_on: Date | None = Field(default=None)
    # For an asset or liability account outside the budget (a loan): the expense category its payments are
    # budgeted under, so paying the EMI spends that category (see services/budget.py).
    payment_category_id: UUID | None = Field(default=None, foreign_key="budget_categories.bcid", nullable=True)
    # Set on the built-in groups under Assets and Liabilities (Bank Accounts, Cash, Investments, Credit Cards, Loans):
    # they cannot be renamed, moved, closed or deleted, and what is made under them starts as the key says.
    system_key: str | None = Field(default=None, max_length=40)
    # For an Income or Expenses account (a "books account"): the budget category it stands for. Several accounts may
    # share one category; an account with none is not budgeted and shows only in the reports.
    category_id: UUID | None = Field(default=None, foreign_key="budget_categories.bcid", nullable=True, index=True)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        return v
