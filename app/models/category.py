from uuid import UUID, uuid4

from pydantic import field_validator
from sqlmodel import Field

from .utils import TimestampMixin
from ..schemas.transaction import Type


class Category(TimestampMixin, table=True):
    __tablename__ = "categories"

    cid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID = Field(index=True, foreign_key="auth.users.id")
    type: Type
    name: str = Field(max_length=40)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        return v
