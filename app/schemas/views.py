"""What the view endpoints (/api/views) answer: one screen of the finode app each, shaped as that screen shows it."""

from datetime import date as Date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from .transaction import RelatedRef

Kind = Literal["expense", "income", "transfer"]


class RowRead(BaseModel):
    """One row of a list of transactions (services/transaction_rows.TransactionRow)."""

    id: UUID
    date: Date
    title: str
    sub: str
    amount: Decimal
    kind: Kind
    # An opening balance or an adjustment against the system's Opening Balances account.
    is_system: bool
    # One account's opening balance: several on one day fold into one row.
    is_opening: bool
    related: RelatedRef | None
    recurring: bool
    by_assistant: str | None


class SummaryRead(BaseModel):
    """How many entries a filter found and, when they all go one way, what they come to ("spent" or "earned")."""

    count: int
    total: Decimal | None
    word: str


class UpcomingRead(BaseModel):
    """An entry dated ahead, as the "upcoming" card lists it."""

    id: UUID
    date: Date
    title: str
    sub: str
    amount: Decimal
    income: bool


class AppliedFilter(BaseModel):
    key: Literal["account", "category", "merchant", "tag"]
    label: str
    name: str


class TransactionsView(BaseModel):
    """A page of the Transactions list for one month."""

    month: str
    is_current: bool
    rows: list[RowRead]
    total: int
    summary: SummaryRead | None
    upcoming: list[UpcomingRead]
    upcoming_total: Decimal | None
    error: str | None
    applied: list[AppliedFilter]


class FilterChoice(BaseModel):
    id: UUID
    name: str
    sub: str


class FilterOptions(BaseModel):
    accounts: list[FilterChoice]
    categories: list[FilterChoice]
    merchants: list[str]


class LineRead(BaseModel):
    """One side's line in a transaction's details."""

    name: str
    amount: Decimal
    posted_on: Date | None


class PersonRef(BaseModel):
    id: UUID
    name: str


class TransactionDetails(BaseModel):
    """What the details sheet shows about one transaction."""

    row: RowRead
    from_label: str
    to_label: str
    from_lines: list[LineRead]
    to_lines: list[LineRead]
    comment: str | None
    tags: list[str]
    related_to: RowRead | None
    related: list[RowRead]
    # An entry made through a person (a loan, a shared bill, a settlement).
    person: PersonRef | None
    # A loan, a borrowing or a bill shared with people: edited here too. Otherwise the person's page looks after it.
    loan_like: bool
    with_names: list[str]
    source: str | None
    source_url: str | None
    external_id: str | None
    added_by: str | None
    changed_by: str | None
