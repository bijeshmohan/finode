from datetime import date as Date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from ..models.transaction import PostingSide


class PostingBase(BaseModel):
    account: UUID
    side: PostingSide
    # Quantity of the account's commodity; how many decimals it may have is checked against that commodity.
    amount: Decimal = Field(decimal_places=8, max_digits=24)

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("amount must be positive!")
        return v


class PostingCreate(PostingBase):
    # What the posting is worth in the transaction's currency. Optional for postings in that
    # currency (it is the amount); required when the account holds something else.
    value: Decimal | None = Field(default=None, decimal_places=8, max_digits=24)

    @field_validator("value")
    @classmethod
    def value_must_be_positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v <= 0:
            raise ValueError("value must be positive!")
        return v


class PostingRead(PostingBase):
    pid: UUID
    transaction: UUID
    # The posting measured in the transaction's currency (equal to `amount` for postings in that currency).
    value: Decimal
    created: datetime
    updated: datetime


class TransactionBase(BaseModel):
    date: Date = Field(default_factory=Date.today)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)


class TransactionCreate(TransactionBase):
    # Code of the currency the transaction balances in; the user's default currency when omitted.
    currency: str | None = Field(default=None, max_length=20)
    postings: list[PostingCreate]

    @model_validator(mode="after")
    def postings_must_balance(self) -> "TransactionCreate":
        validate_balanced_postings(self.postings)
        return self


class TransactionRead(TransactionBase):
    tid: UUID
    # Code of the currency the transaction balances in, e.g. "INR".
    currency: str
    postings: list[PostingRead]
    created: datetime
    updated: datetime


class TransactionUpdate(BaseModel):
    currency: str | None = Field(default=None, max_length=20)
    date: Date | None = Field(default=None)
    payee: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=200)
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

    # With explicit values the postings may be in different commodities, so whether they balance
    # depends on the accounts: the transaction service checks that. Without any, they must add up.
    if any(posting.value is not None for posting in postings):
        return
    debit_total = sum(
        posting.amount for posting in postings if posting.side == PostingSide.DEBIT
    )
    credit_total = sum(
        posting.amount for posting in postings if posting.side == PostingSide.CREDIT
    )
    if debit_total != credit_total:
        raise ValueError("transaction debits and credits must balance!")
