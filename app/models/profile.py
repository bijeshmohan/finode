from uuid import UUID

from sqlalchemy import CheckConstraint
from sqlmodel import Field

from .utils import TimestampMixin


class Profile(TimestampMixin, table=True):
    """Per-user details and application settings; one row per user, one column per setting."""

    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(
            "max_depth_assets >= 0 AND max_depth_liabilities >= 0 AND max_depth_equity >= 0 "
            "AND max_depth_income >= 0 AND max_depth_expenses >= 0",
            name="ck_profiles_max_depth_non_negative",
        ),
    )

    user: UUID = Field(primary_key=True, foreign_key="auth.users.id")
    first_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)
    # Deepest sub-account level allowed under each top-level account; 0 means no limit of the user's own.
    max_depth_assets: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    max_depth_liabilities: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    max_depth_equity: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    max_depth_income: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    max_depth_expenses: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
