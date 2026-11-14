"""What the Add screen saves (/api/entries and the web form alike): the entry's details and its rows as the person chose
them. A row names an account, a category or a person; the server decides what that records (services/entry.py)."""

from decimal import Decimal
from typing import Annotated, Literal
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


class PersonShare(BaseModel):
    """A person a bill is shared with."""

    contact_id: UUID
    # Their share, for a split by amounts, percentages or shares (none for an equal split).
    value: Decimal | None = None
    # What they paid of the bill.
    paid: Decimal | None = None


class ExpenseShare(BaseModel):
    """A bill shared with people, as the Split form describes it. The server works out the shares and what is owed."""

    kind: Literal["expense"] = "expense"
    category_id: UUID | None = None
    # The account you paid from.
    account_id: UUID | None = None
    method: Literal["equal", "exact", "percentage", "shares"] = "equal"
    self_value: Decimal | None = None
    # What you paid; none is whatever the others did not.
    self_paid: Decimal | None = None
    people: list[PersonShare] = Field(default_factory=list)

    def person(self, contact_id: UUID) -> PersonShare | None:
        return next((p for p in self.people if p.contact_id == contact_id), None)


class IncomePart(BaseModel):
    """A person an income is shared with: the part that is theirs, and what they received of it for you."""

    contact_id: UUID
    theirs: Decimal | None = None
    received: Decimal | None = None


class IncomeShare(BaseModel):
    """Income shared with people, as the Split form describes it."""

    kind: Literal["income"] = "income"
    category_id: UUID | None = None
    # The account it was paid into.
    account_id: UUID | None = None
    people: list[IncomePart] = Field(default_factory=list)

    def person(self, contact_id: UUID) -> IncomePart | None:
        return next((p for p in self.people if p.contact_id == contact_id), None)


Share = Annotated[ExpenseShare | IncomeShare, Field(discriminator="kind")]


class EntryForm(BaseModel):
    kind: Literal["expense", "income", "transfer", "other"] = "other"
    date: Day | None = None
    payee: str | None = None
    comment: str | None = None
    tags: list[str] = Field(default_factory=list)
    related_id: UUID | None = None
    # The person an expense or an income names after "@": a gift to or from them, nothing owed.
    payee_contact: UUID | None = None
    rows: list[EntryRow] = Field(default_factory=list)
    # A bill or an income shared with people (the form's Split): its amount, and how it is shared. It has no rows.
    total: Decimal | None = None
    share: Share | None = None


class EntrySaved(BaseModel):
    transaction_id: UUID
    # "transfer": money to or from a person, recorded by the people services (a loan, a borrowing, paying back);
    # "expense-shared" / "income-shared": a bill or an income shared with people.
    recorded: Literal["transaction", "transfer", "expense-shared", "income-shared"]
