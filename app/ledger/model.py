from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass
class LedgerPosting:
    account: str  # colon-separated path, e.g. "Expenses:Food:Groceries"
    amount: Decimal  # debit positive, credit negative
    line: int = 0
    # What the amount is of, as written in the file ("USD", "$", "INFY"); None when written without one.
    commodity: str | None = None
    # What the posting cost in total, when it was bought or sold with another commodity ("@" or "@@").
    cost: Decimal | None = None
    cost_commodity: str | None = None


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
class CommodityDecl:
    """A `commodity` directive: how many decimals the commodity has, and finode's own name/kind tags."""

    symbol: str
    decimals: int | None = None
    name: str | None = None
    kind: str | None = None
    line: int = 0


@dataclass
class PriceDecl:
    """A `P` directive: one unit of `symbol` was worth `price` of `quote` on `date`."""

    date: date
    symbol: str
    price: Decimal
    quote: str | None
    line: int = 0


@dataclass
class Journal:
    accounts: list[AccountDecl] = field(default_factory=list)
    commodities: list[CommodityDecl] = field(default_factory=list)
    prices: list[PriceDecl] = field(default_factory=list)
    transactions: list[LedgerTransaction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
