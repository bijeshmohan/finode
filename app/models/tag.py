from uuid import UUID, uuid4

from sqlalchemy import Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from .utils import TimestampMixin


class Tag(TimestampMixin, table=True):
    """A label a person puts on entries ("goa-trip"). The name is lower case and unique per person, so #EMI and #emi
    are one tag. A tag exists only while an entry carries it: taking it off the last one deletes the row."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user", "name", name="uq_tags_user_name"),)

    tgid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=30)


class TransactionTag(SQLModel, table=True):
    """The tags on an entry (the entry's postings-like children: the repository removes them with the entry)."""

    __tablename__ = "transaction_tags"
    __table_args__ = (Index("ix_transaction_tags_user_tag", "user", "tag_id"),)

    transaction_id: UUID = Field(foreign_key="transactions.tid", primary_key=True)
    tag_id: UUID = Field(foreign_key="tags.tgid", primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
