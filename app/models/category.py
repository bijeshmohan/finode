from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field

from ..schemas.transaction import Type


class Category(SQLModel, table=True):
    __tablename__ = "categories"

    cid: UUID = Field(default_factory=uuid4, primary_key=True)
    type: Type
    name: str = Field(max_length=40)
