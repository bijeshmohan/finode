from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


DEPTH_FIELDS = (
    "max_depth_assets",
    "max_depth_liabilities",
    "max_depth_equity",
    "max_depth_income",
    "max_depth_expenses",
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)
    # 0 = no limit of your own; the application maximum and your existing accounts are checked by the service.
    max_depth_assets: int | None = Field(default=None, ge=0)
    max_depth_liabilities: int | None = Field(default=None, ge=0)
    max_depth_equity: int | None = Field(default=None, ge=0)
    max_depth_income: int | None = Field(default=None, ge=0)
    max_depth_expenses: int | None = Field(default=None, ge=0)

    @field_validator("first_name", "last_name")
    @classmethod
    def blank_means_unset(cls, v: str | None) -> str | None:
        return _clean(v)

    @model_validator(mode="after")
    def depth_must_not_be_null(self) -> "ProfileUpdate":
        for name in DEPTH_FIELDS:
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"the field '{name}' must not be null!")
        return self


class ProfileRead(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    default_currency: str | None = None
    max_depth_assets: int = 0
    max_depth_liabilities: int = 0
    max_depth_equity: int = 0
    max_depth_income: int = 0
    max_depth_expenses: int = 0
    created: datetime
    updated: datetime
