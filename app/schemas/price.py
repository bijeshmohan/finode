from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


class PriceCreate(BaseModel):
    # What is priced, and what the price is quoted in: 1 `commodity` = `price` `quote`.
    commodity: str = Field(max_length=20)
    quote: str = Field(max_length=20)
    date: Date = Field(default_factory=Date.today)
    price: Decimal = Field(gt=0, decimal_places=12, max_digits=28)


class PriceRead(BaseModel):
    pid: UUID
    commodity: str
    quote: str
    date: Date
    price: Decimal
    # True for the shared feed, False for prices the user entered.
    is_global: bool


class RateRead(BaseModel):
    commodity: str
    quote: str
    date: Date
    rate: Decimal | None = None
    # The oldest day any price behind the rate is from.
    as_of: Date | None = None
