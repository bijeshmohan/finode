from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index
from sqlmodel import Field

from .utils import TimestampMixin


class OAuthGrant(TimestampMixin, table=True):
    """What a user let one OAuth app (an AI assistant that signed in through Supabase) do in finode.

    Supabase issues the app's tokens and knows who the user is; it has no notion of read versus
    write, so the access level the user chose on the consent page is kept here.
    """

    __tablename__ = "oauth_grants"
    __table_args__ = (
        CheckConstraint("scope IN ('read', 'write')", name="ck_oauth_grants_scope"),
        Index("uq_oauth_grants_user_client", "user", "client_id", unique=True),
    )

    gid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    # Supabase's id for the registered app.
    client_id: str = Field(max_length=100)
    client_name: str = Field(max_length=80)
    scope: str = Field(max_length=10)
    last_used: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    revoked: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
