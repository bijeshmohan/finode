from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, JSON
from sqlmodel import Field, SQLModel

from .utils import utc_now


class TransactionHistory(SQLModel, table=True):
    """Append-only log of what happened to each transaction: one row per creation, edit and deletion.

    Rows are never updated or deleted, and deliberately carry no foreign key to the transaction, so the
    trace of a deleted transaction survives it. `snapshot` is the transaction as it stood right after
    the action (as it stood when deleted, for a deletion): its fields and postings, by id.
    """

    __tablename__ = "transaction_history"
    __table_args__ = (
        CheckConstraint("action IN ('created', 'updated', 'deleted')", name="ck_transaction_history_action"),
        Index("ix_transaction_history_user_transaction", "user", "transaction_id"),
    )

    hid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    transaction_id: UUID
    action: str = Field(max_length=10)
    at: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))
    # "web", "api", "import", "recurring", "mcp:<token name>"; None when not known.
    via: str | None = Field(default=None, max_length=60)
    snapshot: dict = Field(sa_type=JSON)
