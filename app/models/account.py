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
    )

    aid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = Field(default=None, foreign_key="accounts.aid", nullable=True)
    # What the account holds. Root accounts hold nothing of their own (their total is valued in the default currency).
    # Whether this asset or liability account (a bank, a credit card) is part of the budget (see services/budget.py).
    on_budget: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    commodity_id: UUID | None = Field(default=None, foreign_key="commodities.cid", nullable=True)
    # For an asset or liability account outside the budget (a loan): the expense category its payments are
    # budgeted under, so paying the EMI spends that category (see services/budget.py).
    payment_category_id: UUID | None = Field(default=None, foreign_key="accounts.aid", nullable=True)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        return v
