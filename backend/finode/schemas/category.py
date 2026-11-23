"""What the API takes and returns for categories, and what deleting or merging one did."""

from datetime import date as Date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from ..category_icons import check_icon
from .account import MergeResult, clean_name

CategoryKindName = Literal["spending", "earning"]


class CategoryCreate(BaseModel):
    name: str = Field(max_length=40)
    kind: CategoryKindName
    # One of finode's category icons (finode/category_icons.py): a new category always names one.
    icon: str
    details: str | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_name(value)

    @field_validator("icon")
    @classmethod
    def _known_icon(cls, value: str) -> str:
        return check_icon(value)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)
    icon: str | None = None

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        return None if value is None else clean_name(value)

    @field_validator("icon")
    @classmethod
    def _known_icon(cls, value: str | None) -> str | None:
        return None if value is None else check_icon(value)


class CategoryRead(BaseModel):
    id: UUID
    name: str
    kind: CategoryKindName
    icon: str
    details: str | None = None
    closed_on: Date | None = None
    # "uncategorised.spending" / "uncategorised.earning" on the built-in ones.
    system_key: str | None = None


class CategoryDeleteResult(BaseModel):
    # "deleted" (unused: gone for good) or "closed" (it has history: kept, no longer offered).
    outcome: Literal["deleted", "closed"]
    category: CategoryRead


class CategoryMergeResult(MergeResult):
    """What folding one category into another did (or, for a dry run, would do)."""

    # The months in which the folded category had a planned amount, now added to the other's.
    plan_months_moved: int
