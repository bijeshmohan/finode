from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from .utils import TimestampMixin, utc_now


class Contact(TimestampMixin, table=True):
    """A person the owner has money dealings with. Not an account: the ledger side is the two accounts in
    `contact_accounts`. Archiving hides a contact and keeps everything it did."""

    __tablename__ = "contacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=30)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=500)
    archived_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class ContactAccount(SQLModel, table=True):
    """The ledger accounts that stand for a contact: "Due from X" (an asset, the contact owes the owner) and
    "Due to X" (a liability, the owner owes the contact)."""

    __tablename__ = "contact_accounts"
    __table_args__ = (
        UniqueConstraint("contact_id", "role", name="uq_contact_accounts_contact_role"),
        UniqueConstraint("account_id", name="uq_contact_accounts_account"),
        CheckConstraint("role IN ('receivable', 'payable')", name="ck_contact_accounts_role"),
        Index("ix_contact_accounts_user", "user_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    contact_id: UUID = Field(foreign_key="contacts.id")
    account_id: UUID = Field(foreign_key="accounts.id")
    role: str = Field(max_length=10)
    created: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))
