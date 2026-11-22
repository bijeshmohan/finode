"""A person's profile: their details and settings, one typed column per setting."""

from uuid import UUID

from sqlmodel import Field

from .utils import TimestampMixin

DEFAULT_TYPE_ORDER = "assets.bank,assets.cash,liabilities.cards,assets.wallet"


class Profile(TimestampMixin, table=True):
    """Per-user details and application settings; one row per user, one column per setting."""

    __tablename__ = "profiles"
    user_id: UUID = Field(primary_key=True, foreign_key="auth.users.id")
    first_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)
    # The one currency the whole ledger is kept in (ISO 4217 code, see currencies.py); changing it relabels, it converts nothing.
    currency: str = Field(default="INR", max_length=3, sa_column_kwargs={"server_default": "INR"})
    # The order the person puts the four account types in (services/account_types.py TYPE_KEYS, comma-joined): the
    # Accounts page's rows, the pickers' headings and the assistants' list follow it.
    account_type_order: str = Field(
        default=DEFAULT_TYPE_ORDER, max_length=80, sa_column_kwargs={"server_default": DEFAULT_TYPE_ORDER}
    )
