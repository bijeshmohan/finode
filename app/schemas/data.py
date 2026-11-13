"""What an import reports, and what the data page offers (Erase, Delete my account)."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ImportSummary(BaseModel):
    """What an import will do (or did); errors mean nothing is saved."""

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    new_accounts: list[str] = Field(default_factory=list)
    # Expenses and Income paths in the file are categories here: the ones that are new.
    new_categories: list[str] = Field(default_factory=list)
    accounts_reused: int = 0
    transactions: int = 0
    skipped_empty: int = 0
    date_from: date | None = None
    date_to: date | None = None
    # Totals of the imported accounts.
    assets: Decimal = Decimal("0.00")
    liabilities: Decimal = Decimal("0.00")


class DataOptions(BaseModel):
    """What the data page offers: import and restore need empty books; Erase and Delete ask for `confirm_word`."""

    can_import: bool
    can_restore: bool
    confirm_word: str
    # Delete my account can also remove the sign-in (Supabase's admin key is set on the server).
    can_delete_login: bool


class Confirmation(BaseModel):
    """The word the person typed to confirm (their email, or DELETE when the account has none)."""

    confirm: str = ""
