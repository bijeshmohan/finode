from decimal import Decimal
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field


class Account(SQLModel, table=True):
    __tablename__ = "accounts"

    aid: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(max_length=40)
    details: str | None = Field(default=None, max_length=200)
    balance: Decimal = Field(
        default=Decimal("0.00"),
        decimal_places=2,
        max_digits=12,
    )
