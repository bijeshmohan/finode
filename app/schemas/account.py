from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class AccountBase(BaseModel):
    name: str = Field(max_length=40)
    details: str | None = Field(max_length=200)
    balance: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
    )


class AccountCreate(AccountBase):
    ...


class AccountRead(AccountBase):
    aid: UUID


class AccountUpdate(AccountBase):
    ...
