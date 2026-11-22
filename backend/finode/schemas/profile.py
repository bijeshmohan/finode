"""What the API takes and returns for a person's profile and the currencies they can choose."""

from datetime import datetime
from typing import get_args

from pydantic import BaseModel, Field, field_validator, model_validator

from .account import AccountType


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)
    # Code of the currency the whole ledger is kept in (ISO 4217, e.g. "INR"). Changing it relabels every amount; nothing is converted.
    default_currency: str | None = Field(default=None, max_length=20)
    # The four account types in the person's order: each key once (assets.bank, assets.cash, liabilities.cards,
    # assets.wallet).
    account_type_order: list[AccountType] | None = None

    @field_validator("first_name", "last_name")
    @classmethod
    def blank_means_unset(cls, v: str | None) -> str | None:
        return _clean(v)

    @model_validator(mode="after")
    def default_currency_must_not_be_null(self) -> ProfileUpdate:
        if "default_currency" in self.model_fields_set and not self.default_currency:
            raise ValueError("the field 'default_currency' must not be empty!")
        if self.account_type_order is not None and sorted(self.account_type_order) != sorted(get_args(AccountType)):
            raise ValueError("give each of the four types once!")
        return self


class ProfileRead(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    default_currency: str | None = None
    account_type_order: list[AccountType]
    created: datetime
    updated: datetime


class CurrencyRead(BaseModel):
    code: str
    name: str
    # Decimal places the currency keeps.
    decimals: int
    symbol: str | None = None
