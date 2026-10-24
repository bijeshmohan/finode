from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from .day import Day


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)
    # Code of the currency the whole ledger is kept in (ISO 4217, e.g. "INR"). Changing it relabels every amount; nothing is converted.
    default_currency: str | None = Field(default=None, max_length=20)
    # Close the books up to and including this day (a day before today at the latest); null opens them again.

    @field_validator("first_name", "last_name")
    @classmethod
    def blank_means_unset(cls, v: str | None) -> str | None:
        return _clean(v)

    @model_validator(mode="after")
    def default_currency_must_not_be_null(self) -> "ProfileUpdate":
        if "default_currency" in self.model_fields_set and not self.default_currency:
            raise ValueError("the field 'default_currency' must not be empty!")
        return self


class ProfileRead(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    default_currency: str | None = None
    created: datetime
    updated: datetime
