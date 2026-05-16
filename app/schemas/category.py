from uuid import UUID

from pydantic import BaseModel, Field

from .transaction import Type


class CategoryBase(BaseModel):
    type: Type
    name: str = Field(max_length=40)


class CategoryCreate(CategoryBase):
    ...


class CategoryRead(CategoryBase):
    cid: UUID


class CategoryUpdate(BaseModel):
    type: Type | None = Field(default=None)
    name: str | None = Field(default=None, max_length=40)
