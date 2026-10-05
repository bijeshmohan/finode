from datetime import date as Date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class AccountBase(BaseModel):
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        if ":" in v:
            raise ValueError("name must not contain ':'!")
        return v


class AccountCreate(AccountBase):
    balance: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
    )


class AccountRead(AccountBase):
    aid: UUID
    # Code of what the account holds (e.g. "INR", "BTC"); root accounts hold nothing of their own.
    commodity: str | None = None
    balance: Decimal = Field(decimal_places=2, max_digits=12)
    created: datetime
    updated: datetime


class AccountUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)
    parent_id: UUID | None = None
    balance: Decimal | None = Field(
        default=None,
        decimal_places=2,
        max_digits=12,
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v:
            raise ValueError("name must not be empty!")
        if ":" in v:
            raise ValueError("name must not contain ':'!")
        return v


class RegisterEntry(BaseModel):
    tid: UUID
    date: Date
    payee: str | None
    comment: str | None
    counter_accounts: list[str]
    change: Decimal = Field(decimal_places=2, max_digits=12)
    balance: Decimal = Field(decimal_places=2, max_digits=12)
