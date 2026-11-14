"""The rows of a list of transactions, as every list shows them (the web pages and the React app's view endpoints):
what each row is called, its second line, which way the money went, and the lists' summary and filter choices."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date as Date
from decimal import Decimal
from uuid import UUID

from ..models.transaction import PostingSide
from ..schemas import AccountRead
from ..schemas.category import CategoryRead
from ..schemas.coming_up import ComingUpLine
from ..schemas.transaction import PostingBase, RelatedRef, TransactionRead
from .account_tree import build_tree, without_contacts
from .transaction import TransactionService

PAGE_SIZE = 25

# How many entries dated ahead the transactions page lists under "upcoming".
UPCOMING_LIMIT = 100
KIND_FILTERS = {"expense": "expense", "income": "income", "transfer": "transfer"}
HOME_FIRST = 8  # Home starts with this many entries (a day is finished) and "Show more" brings this many each time
HOME_MORE = 10
OPENING_BALANCES = "Opening Balances"
STOCK_OPENING_NOTE = "Initial account balance"


@dataclass
class UpcomingItem:
    """One entry dated ahead, as the "upcoming" card shows it (see partials/upcoming.html)."""

    transaction_id: UUID
    date: Date
    title: str
    sub: str
    amount: Decimal
    income: bool = False


@dataclass
class TransactionRow:
    transaction: TransactionRead
    debits: list[str]
    credits: list[str]
    amount: Decimal
    kind: str  # expense | income | transfer
    # The earlier entry this one is related to, with its date and amount, when a list loaded it (`list_rows`).
    related: RelatedRef | None = None

    @property
    def is_system(self) -> bool:
        """An opening balance or an adjustment: bookkeeping against the system's Opening Balances account."""
        return OPENING_BALANCES in self.credits or OPENING_BALANCES in self.debits

    @property
    def is_opening(self) -> bool:
        """One account's opening balance (several on one day fold into one row)."""
        return self.transaction.payee == "Opening balance"

    @property
    def title(self) -> str:
        """The payee; without one, where the money went."""
        return self.transaction.payee or ", ".join(self.debits)

    @property
    def sub(self) -> str:
        """The quiet second line: where the money came from (and went, when the title is a payee), then the note. An
        opening balance or adjustment names just the account: "Opening Balances" and the stock note say nothing."""
        t = self.transaction
        if self.is_system:
            line = ", ".join(n for n in self.credits + self.debits if n != OPENING_BALANCES)
        elif t.payee:
            line = f"{', '.join(self.credits)} \u2192 {', '.join(self.debits)}"
        else:
            line = ", ".join(self.credits)
        note = "" if self.is_system and t.comment == STOCK_OPENING_NOTE else (t.comment or "")
        return f"{line} · {note}" if note else line

    @property
    def recurring(self) -> bool:
        return bool(self.transaction.recurring_id) or self.transaction.created_via == "recurring"

    @property
    def by_assistant(self) -> str | None:
        """ "Added by Claude" or "Changed by Claude" when an AI assistant made or last changed the entry."""
        made, changed = self.transaction.created_via or "", self.transaction.updated_via or ""
        if made.startswith("mcp:"):
            return f"Added by {made[4:]}"
        if changed.startswith("mcp:"):
            return f"Changed by {changed[4:]}"
        return None


@dataclass
class AccountIndex:
    names: dict[UUID, str]
    roots: dict[UUID, str]
    # The categories' names: a line on Expenses or Income is named for what it was for.
    categories: dict[UUID, str] = field(default_factory=dict)

    @classmethod
    def build(cls, accounts: list[AccountRead], categories: list[CategoryRead] | None = None) -> AccountIndex:
        names = {a.id: a.name for a in accounts}
        roots = {node.account.id: root.account.name for root in build_tree(accounts) for node in root.walk()}
        return cls(names, roots, {c.id: c.name for c in categories or []})

    def line_name(self, posting: PostingBase | ComingUpLine) -> str:
        """What a line is called in a list: its category when it sits on Expenses or Income, else its account."""
        if self.roots.get(posting.account_id) in ("Expenses", "Income"):
            return self.categories.get(posting.category_id, "Uncategorised") if posting.category_id else "Uncategorised"
        return self.names.get(posting.account_id, "?")


def to_row(transaction: TransactionRead, index: AccountIndex) -> TransactionRow:
    def side_names(side: PostingSide) -> list[str]:
        found: list[str] = []
        for posting in transaction.postings:
            name = index.line_name(posting)
            if posting.side == side and name not in found:
                found.append(name)
        return found

    def touches(root: str, side: PostingSide) -> bool:
        return any(p.side == side and index.roots.get(p.account_id) == root for p in transaction.postings)

    if touches("Expenses", PostingSide.DEBIT):
        kind = "expense"
    elif touches("Income", PostingSide.CREDIT):
        kind = "income"
    else:
        kind = "transfer"

    amount = sum(
        (p.amount for p in transaction.postings if p.side == PostingSide.DEBIT),
        Decimal("0.00"),
    )
    return TransactionRow(
        transaction=transaction,
        debits=side_names(PostingSide.DEBIT),
        credits=side_names(PostingSide.CREDIT),
        amount=amount,
        kind=kind,
    )


def list_rows(
    chunk: list[TransactionRead], index: AccountIndex, transactions: TransactionService
) -> list[TransactionRow]:
    """The rows of a list, each with what it is related to (two more queries when anything is, none otherwise)."""
    refs = transactions.related_refs(t.related_id for t in chunk)
    rows = [to_row(t, index) for t in chunk]
    for row in rows:
        row.related = refs.get(row.transaction.related_id) if row.transaction.related_id else None
    return rows


@dataclass
class Summary:
    """How many entries match and, when they all go one way, what they come to ("spent" or "earned")."""

    count: int
    total: Decimal | None
    word: str


def summary_of(found: list[TransactionRead], index: AccountIndex) -> Summary:
    """How many entries match and, when they all go one way, what they come to."""
    rows = [to_row(t, index) for t in found]
    kinds = {r.kind for r in rows}
    word = {"expense": "spent", "income": "earned"}.get(next(iter(kinds)), "") if len(kinds) == 1 else ""
    return Summary(len(rows), sum((r.amount for r in rows), Decimal(0)) if word else None, word)


def upcoming_items(ahead: Iterable[TransactionRead], index: AccountIndex) -> list[UpcomingItem]:
    """Entries dated ahead as the "upcoming" card lists them, soonest first."""
    items = []
    for t in sorted(ahead, key=lambda t: (t.date, t.created)):
        r = to_row(t, index)
        sub = f"{', '.join(r.credits)} \u2192 {', '.join(r.debits)}" if t.payee else ", ".join(r.credits)
        items.append(UpcomingItem(t.id, t.date, t.payee or ", ".join(r.debits), sub, r.amount, r.kind == "income"))
    return items


def filter_options(
    all_accounts: list[AccountRead], categories: list[CategoryRead], transactions: TransactionService
) -> dict:
    """The choices behind the Filter sheet: accounts (assets, liabilities, equity), categories, payees."""
    accounts: list[dict] = []
    for root in without_contacts(build_tree(all_accounts)):
        if root.account.name in ("Expenses", "Income"):
            continue
        parents: dict[int, str] = {}
        for node in root.walk():
            parents[node.depth] = node.account.name
            if node.depth == 0:
                continue
            sub = parents.get(node.depth - 1) if node.depth > 1 else ""
            accounts.append({"id": str(node.account.id), "name": node.account.name, "sub": sub})
    names = {c.id: c.name for c in categories}
    found = [
        {"id": str(c.id), "name": c.name, "sub": names.get(c.parent_id, "") if c.parent_id else ""} for c in categories
    ]
    return {"accounts": accounts, "categories": found, "merchants": [name for name, _ in transactions.payees()]}


def related_info(
    transactions: TransactionService, index: AccountIndex, transaction_id: UUID | None
) -> TransactionRow | None:
    """The entry a form or sheet says another is related to, as a row (payee, date, amount); None when there is none."""
    if transaction_id is None:
        return None
    found = transactions.read(transaction_id)
    return to_row(found, index) if found is not None else None
