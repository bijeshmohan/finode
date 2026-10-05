from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class LedgerPosting:
    account: str  # colon-separated path, e.g. "Expenses:Food:Groceries"
    amount: Decimal  # debit positive, credit negative
    line: int = 0


@dataclass
class LedgerTransaction:
    date: date
    payee: str
    notes: list[str]
    postings: list[LedgerPosting]
    line: int = 0


@dataclass
class AccountDecl:
    name: str
    note: str | None = None
    line: int = 0


@dataclass
class Journal:
    accounts: list[AccountDecl] = field(default_factory=list)
    transactions: list[LedgerTransaction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
