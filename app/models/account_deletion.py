from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, Index
from sqlmodel import Field, SQLModel

from .utils import utc_now


class AccountDeletion(SQLModel, table=True):
    """What an account or category looked like when it was deleted for good (only an unused one can be: no
    entries, no sub-accounts, in no rule), so it can be brought back. Rows are only ever added, and carry no
    foreign key to the account, so the trace survives it.

    `snapshot` holds its name, parent, note, budget flag, payment category, place among its siblings, the
    amounts planned for it in the budget and the accounts whose payments were budgeted under it.
    """

    __tablename__ = "account_deletions"
    __table_args__ = (Index("ix_account_deletions_user_account", "user_id", "account_id"),)

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    account_id: UUID
    at: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))
    snapshot: dict = Field(sa_type=JSON)
