from datetime import date as Date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field


class Transaction(SQLModel, table=True):
    __tablename__ = "transactions"

    tid: UUID = Field(default_factory=uuid4, primary_key=True)
    amount: Decimal = Field(decimal_places=2, max_digits=12)
    source: UUID | None = Field(default=None, foreign_key="accounts.aid")
    destination: UUID | None = Field(default=None, foreign_key="accounts.aid")
    category: UUID = Field(foreign_key="categories.cid")
    date: Date = Field(default_factory=Date.today)
    note: str | None = Field(max_length=40)
    details: str | None = Field(max_length=200)
