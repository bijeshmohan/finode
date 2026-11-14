"""What the Add screen saves (/api/entries and the web form alike): the entry's details and its rows as the person chose
them. A row names an account, a category or a person; the server decides what that records (services/entry.py)."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from ..models.transaction import PostingSide
from .day import Day


class EntryRow(BaseModel):
    # An account, a category (the line posts on Expenses or Income with it) or a person (a loan or a borrowing).
    choice: UUID
    side: PostingSide
    amount: Decimal
    # What a payment from the budget into an account outside it (a loan, a fund) was for.
    category_id: UUID | None = None
    # The day the account posts this line, when it is not the entry's own.
    posted_on: Day | None = None


class EntryForm(BaseModel):
    kind: Literal["expense", "income", "transfer", "other"] = "other"
    date: Day | None = None
    payee: str | None = None
    comment: str | None = None
    tags: list[str] = Field(default_factory=list)
    related_id: UUID | None = None
    # The person an expense or an income names after "@": a gift to or from them, nothing owed.
    payee_contact: UUID | None = None
    rows: list[EntryRow]


class EntrySaved(BaseModel):
    transaction_id: UUID
    # "transfer": money to or from a person, recorded by the people services (a loan, a borrowing, paying back).
    recorded: Literal["transaction", "transfer"]
