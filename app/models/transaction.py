from datetime import date as Date
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import field_validator, model_validator
from sqlmodel import Field

from .utils import TimestampMixin


class Transaction(TimestampMixin, table=True):
    __tablename__ = "transactions"

    tid: UUID = Field(default_factory=uuid4, primary_key=True)
    amount: Decimal = Field(decimal_places=2, max_digits=12)
    source: UUID | None = Field(default=None, foreign_key="accounts.aid")
    destination: UUID | None = Field(default=None, foreign_key="accounts.aid")
    category: UUID = Field(foreign_key="categories.cid")
    date: Date = Field(default_factory=Date.today)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)

    @field_validator("amount")
    @classmethod
    def amount_must_not_be_zero(cls, v: Decimal) -> Decimal:
        if v == 0:
            raise ValueError("amount must not be zero")
        return v

    @model_validator(mode="after")
    def source_and_destination_must_not_be_same(self) -> "Transaction":
        if (self.source is not None and self.destination is not None) and self.source == self.destination:
            raise ValueError("both 'source' and 'destination' must not be the same!")
        return self
