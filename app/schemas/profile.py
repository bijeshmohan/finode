from datetime import datetime

from pydantic import BaseModel, Field, field_validator


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


class ProfileUpdate(BaseModel):
    first_name: str | None = Field(default=None, max_length=40)
    last_name: str | None = Field(default=None, max_length=40)

    @field_validator("first_name", "last_name")
    @classmethod
    def blank_means_unset(cls, v: str | None) -> str | None:
        return _clean(v)


class ProfileRead(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    created: datetime
    updated: datetime
