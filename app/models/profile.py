from datetime import date as Date
from uuid import UUID

from sqlalchemy import false, true
from sqlmodel import Field

from .utils import TimestampMixin


class Profile(TimestampMixin, table=True):
    """Per-user details and application settings; one row per user, one column per setting."""

    __tablename__ = "profiles"
    user: UUID = Field(primary_key=True, foreign_key="auth.users.id")
    first_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)
    # The one currency the whole ledger is kept in (ISO 4217 code, see currencies.py); changing it relabels, it converts nothing.
    currency: str = Field(default="INR", max_length=3, sa_column_kwargs={"server_default": "INR"})
    # Period lock: nothing dated on or before this day can be added, changed or deleted (see services/lock.py).
    locked_through: Date | None = Field(default=None)
    # Show the rarely used features (targets, lock, pinning, closing...). Off hides them, never the data.
    advanced: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
    # Which sections of the Plan the person uses besides Spend (the chips on the Plan page). Off hides a section, never its data.
    plan_build: bool = Field(default=True, sa_column_kwargs={"server_default": true()})
    plan_earn: bool = Field(default=False, sa_column_kwargs={"server_default": false()})
