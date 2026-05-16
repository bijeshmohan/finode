from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AccountBase(BaseModel):
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    balance: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        return v

class AccountCreate(AccountBase):
    ...


class AccountRead(AccountBase):
    aid: UUID
    created: datetime
    updated: datetime


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)
    balance: Decimal | None = Field(
        default=None,
        decimal_places=2,
        max_digits=12,
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        return v
