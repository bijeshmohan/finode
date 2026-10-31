from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, Index
from sqlmodel import Field, SQLModel

from .utils import utc_now


class AccountHistory(SQLModel, table=True):
    """Append-only log of what happened to each account or category: one row per creation, change, closing,
    reopening, restoring and deletion (the built-in roots and groups are not logged).

    Rows are never updated or deleted and carry no foreign key to the account, so the trace of a deleted one
    survives it. `snapshot` is the account as it stood right after the action (as it stood when deleted, for a
    deletion): name, path, parent, note, budget flag, payment category, closing day. A merge ends with a deletion
    whose snapshot also names the account it was merged into.
    """

    __tablename__ = "account_history"
    __table_args__ = (
        CheckConstraint(
            "action IN ('created', 'updated', 'closed', 'reopened', 'restored', 'deleted')",
            name="ck_account_history_action",
        ),
        Index("ix_account_history_user_account", "user_id", "account_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    account_id: UUID
    action: str = Field(max_length=10)
    at: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))
    # "web", "api" or "mcp:<token name>"; None when not known.
    via: str | None = Field(default=None, max_length=60)
    snapshot: dict = Field(sa_type=JSON)
