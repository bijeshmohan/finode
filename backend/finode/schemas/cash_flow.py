"""What the conversion to cash flow would do (a plan, shown before anything changes) and what it did."""

from datetime import date as Date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, PrivateAttr


class AccountMove(BaseModel):
    account_id: UUID
    # Where the account is now ("Liabilities:Loans:Home Loan") and what becomes of it ("deleted", or its new path).
    path: str
    becomes: str


class EntryChange(BaseModel):
    transaction_id: UUID | None = None
    recurring_id: UUID | None = None
    day: Date | None = None
    # One line for a person to read: "2026-10-05 EMI: Home Loan → Expenses (Home Loan)".
    summary: str


class ConversionPlan(BaseModel):
    retired: list[AccountMove] = []
    moved: list[AccountMove] = []
    rewritten: list[EntryChange] = []
    deleted: list[EntryChange] = []
    new_categories: list[str] = []
    # Accounts with no type to give them (finode never guesses one): `apply` refuses while there are any.
    undecided_accounts: list[str] = []
    # Months ("2026-10") where a payment lands in a category it never had: it shows as spent there, unassigned.
    overspent_months: list[str] = []
    # What `apply` carries out, worked out with the plan (not shown).
    _work: Any = PrivateAttr(default=None)


class ConversionResult(BaseModel):
    rewritten: int = 0
    deleted: int = 0
    recurring_rewritten: int = 0
    recurring_ended: int = 0
    accounts_deleted: int = 0
    categories_made: list[str] = []
