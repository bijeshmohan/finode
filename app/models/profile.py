from uuid import UUID

from sqlmodel import Field

from .utils import TimestampMixin


class Profile(TimestampMixin, table=True):
    """Per-user details and application settings; one row per user, one column per setting."""

    __tablename__ = "profiles"

    user: UUID = Field(primary_key=True, foreign_key="auth.users.id")
    first_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)
