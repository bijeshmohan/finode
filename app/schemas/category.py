from datetime import date as Date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .account import clean_name

CategoryKindName = Literal["spending", "earning"]


class CategoryCreate(BaseModel):
    name: str = Field(max_length=40)
    kind: CategoryKindName
    # The group it goes in (a category with no parent); leave it out to make a group or a category of its own.
    parent_id: UUID | None = None
    details: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_name(value)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)
    # Send null to take it out of its group; leave it out to keep it where it is.
    parent_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return None if value is None else clean_name(value)


class CategoryRead(BaseModel):
    id: UUID
    name: str
    kind: CategoryKindName
    parent_id: UUID | None = None
    details: str | None = None
    closed_on: Date | None = None
    # "uncategorised.spending" / "uncategorised.earning" on the built-in ones.
    system_key: str | None = None
    # "Food:Groceries": the group and the category.
    path: str


class CategoryDeleteResult(BaseModel):
    # "deleted" (unused: gone for good) or "closed" (it has history: kept, no longer offered).
    outcome: Literal["deleted", "closed"]
    category: CategoryRead
