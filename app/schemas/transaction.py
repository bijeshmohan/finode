from datetime import date as Date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..models.transaction import PostingSide


class PostingBase(BaseModel):
    account: UUID
    side: PostingSide
    amount: Decimal = Field(decimal_places=2, max_digits=12)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive!")
        return v


class PostingCreate(PostingBase):
    ...


class PostingRead(PostingBase):
    pid: UUID
    transaction: UUID
    created: datetime
    updated: datetime


class TransactionBase(BaseModel):
    date: Date = Field(default_factory=Date.today)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)


class TransactionCreate(TransactionBase):
    postings: list[PostingCreate]

    @model_validator(mode="after")
    def postings_must_balance(self) -> "TransactionCreate":
        validate_balanced_postings(self.postings)
        return self


class TransactionRead(TransactionBase):
    tid: UUID
    postings: list[PostingRead]
    created: datetime
    updated: datetime


class TransactionUpdate(BaseModel):
    date: Date | None = Field(default=None)
    note: str | None = Field(default=None, max_length=40)
    details: str | None = Field(default=None, max_length=200)
    postings: list[PostingCreate] | None = Field(default=None)

    @model_validator(mode="after")
    def non_nullable_fields_must_not_be_null(self) -> "TransactionUpdate":
        if "date" in self.model_fields_set and self.date is None:
            raise ValueError("the field 'date' must not be null!")
        return self

    @model_validator(mode="after")
    def postings_must_balance(self) -> "TransactionUpdate":
        if self.postings is not None:
            validate_balanced_postings(self.postings)
        return self


def validate_balanced_postings(postings: list[PostingCreate]) -> None:
    if len(postings) < 2:
        raise ValueError("transactions must contain at least two postings!")

    debit_total = sum(
        posting.amount for posting in postings if posting.side == PostingSide.DEBIT
    )
    credit_total = sum(
        posting.amount for posting in postings if posting.side == PostingSide.CREDIT
    )
    if debit_total != credit_total:
        raise ValueError("transaction debits and credits must balance!")
