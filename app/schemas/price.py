from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field
from ..clock import local_today


class PriceCreate(BaseModel):
    # What is priced, and what the price is quoted in: 1 `commodity` = `price` `quote`.
    commodity: str = Field(max_length=20)
    quote: str = Field(max_length=20)
    date: Date = Field(default_factory=local_today)
    price: Decimal = Field(gt=0, decimal_places=12, max_digits=28)


class PriceRead(BaseModel):
    pid: UUID
    commodity: str
    quote: str
    date: Date
    price: Decimal


class RateRead(BaseModel):
    commodity: str
    quote: str
    date: Date
    rate: Decimal | None = None
    # The oldest day any price behind the rate is from.
    as_of: Date | None = None
