from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import field_validator
from sqlmodel import Field

from .utils import TimestampMixin


class Account(TimestampMixin, table=True):
    __tablename__ = "accounts"

    aid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
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
