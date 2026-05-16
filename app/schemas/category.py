from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .transaction import Type


class CategoryBase(BaseModel):
    type: Type
    name: str = Field(max_length=40)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        return v


class CategoryCreate(CategoryBase):
    ...


class CategoryRead(CategoryBase):
    cid: UUID
    created: datetime
    updated: datetime


class CategoryUpdate(BaseModel):
    type: Type | None = Field(default=None)
    name: str | None = Field(default=None, max_length=40)

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("name must not be empty!")
        return v
