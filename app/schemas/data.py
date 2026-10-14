from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class ImportSummary(BaseModel):
    """What an import will do (or did); errors mean nothing is saved."""

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    new_accounts: list[str] = Field(default_factory=list)
    accounts_reused: int = 0
    transactions: int = 0
    # Commodities the file brings that finode does not know yet (they become your own).
    new_commodities: list[str] = Field(default_factory=list)
    # Commodities other than the default currency that the imported accounts hold.
    other_commodities: list[str] = Field(default_factory=list)
    prices: int = 0
    skipped_empty: int = 0
    date_from: date | None = None
    date_to: date | None = None
    # Totals of the accounts that hold the default currency only.
    assets: Decimal = Decimal("0.00")
    liabilities: Decimal = Decimal("0.00")
