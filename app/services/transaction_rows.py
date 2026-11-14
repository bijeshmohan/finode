"""The rows of a list of transactions, as every list shows them (the web pages and the React app's view endpoints):
what each row is called, its second line, which way the money went, and the lists' summary and filter choices."""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date as Date
from datetime import timedelta
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ..models.transaction import PostingSide
from ..schemas import AccountRead
from ..schemas.account import RegisterEntry
from ..schemas.category import CategoryRead
from ..schemas.coming_up import ComingUpLine
from ..schemas.transaction import PostingBase, RelatedRef, TransactionRead
from ..tags import clean_tag
from .account_tree import build_tree, without_contacts
from .contact import ContactService
from .transaction import TransactionService

PAGE_SIZE = 25

# How many entries dated ahead the transactions page lists under "upcoming".
UPCOMING_LIMIT = 100
KIND_FILTERS = {"expense": "expense", "income": "income", "transfer": "transfer"}
HOME_FIRST = 8  # Home starts with this many entries (a day is finished) and "Show more" brings this many each time
HOME_MORE = 10
RowKind = Literal["expense", "income", "transfer"]
FilterKey = Literal["account", "category", "merchant", "tag"]
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
    kind: RowKind
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

    kind: RowKind
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


def day_totals(rows: list[TransactionRow]) -> dict[Date, Decimal]:
    """What was spent each day (expenses only), for the days with more than one entry: a single entry's total would just
    repeat its row. A day is never split between pages, so a page's rows hold whole days."""
    by_day: dict[Date, list[TransactionRow]] = {}
    for row in rows:
        by_day.setdefault(row.transaction.date, []).append(row)
    totals = {}
    for day, items in by_day.items():
        spent = sum((r.amount for r in items if r.kind == "expense"), Decimal(0))
        if spent and len(items) > 1:
            totals[day] = spent
    return totals


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


def origin_label(origin: str | None) -> str | None:
    """Who entered or changed a transaction, for people: "Claude (AI assistant)", "an import"."""
    if not origin:
        return None
    if origin.startswith("mcp:"):
        return f"{origin[4:]} (AI assistant)"
    return {"web": "the app", "api": "the API", "import": "an import", "recurring": "a recurring transaction"}.get(
        origin, origin
    )


# ---- one month of the list (the Transactions page and its "Show more") ------------------------------------------------


@dataclass
class ListFilters:
    """What the list is narrowed to, as the page's address gives it (ids as text: a bad one is the person's typo)."""

    account: str = ""
    category: str = ""
    merchant: str = ""
    tag: str = ""
    q: str = ""
    kind: str = ""

    @property
    def narrowing(self) -> bool:
        """A filter that the summary line adds up (search and kind do not)."""
        return bool(self.account or self.category or self.merchant.strip() or clean_tag(self.tag))


@dataclass
class Applied:
    key: FilterKey
    label: str
    name: str


@dataclass
class MonthList:
    when: Date
    is_current: bool
    rows: list[TransactionRow]
    total: int
    summary: Summary | None
    upcoming: list[UpcomingItem]
    error: str | None
    applied: list[Applied]

    @property
    def upcoming_total(self) -> Decimal | None:
        """What the schedule comes to; none when something coming in is mixed with what is going out."""
        if not self.upcoming or any(u.income for u in self.upcoming):
            return None
        return sum((u.amount for u in self.upcoming), Decimal(0))


def applied_filters(filters: ListFilters, index: AccountIndex) -> list[Applied]:
    """What is filtered, named as the person knows it."""
    out = []
    keys: tuple[tuple[FilterKey, str], ...] = (
        ("account", "Account"),
        ("category", "Category"),
        ("merchant", "Merchant"),
        ("tag", "Tag"),
    )
    for key, label in keys:
        value = getattr(filters, key).strip()
        if not value:
            continue
        if key == "tag":
            name = f"#{clean_tag(value)}"
        elif key == "merchant":
            name = value
        else:
            try:
                name = index.names.get(UUID(value)) or index.categories.get(UUID(value), "?")
            except ValueError:
                name = "?"
        out.append(Applied(key, label, name))
    return out


def month_list(
    transactions: TransactionService,
    index: AccountIndex,
    when: Date,
    today: Date,
    filters: ListFilters,
    offset: int = 0,
    limit: int = PAGE_SIZE,
) -> MonthList:
    """A page of one month's entries, newest first, up to today (a day is never split between pages); with a filter,
    the summary of everything it matches; on the first page of the current month, what is dated ahead."""
    is_current = when == today.replace(day=1)
    last = when.replace(day=calendar.monthrange(when.year, when.month)[1])
    kind = KIND_FILTERS.get(filters.kind)
    applied = applied_filters(filters, index)
    try:
        account = UUID(filters.account) if filters.account else None
        also = UUID(filters.category) if filters.category else None
    except ValueError as e:
        return MonthList(when, is_current, [], 0, None, [], f"Invalid filter: {e}", applied)
    who, tag, q = filters.merchant.strip() or None, clean_tag(filters.tag) or None, filters.q.strip()
    try:
        chunk, total = transactions.page(offset, limit, account, when, min(last, today), q, kind, also, who, tag)
        everything = (
            transactions.list(account, when, min(last, today), None, 0, q, kind, also, who, tag=tag)
            if filters.narrowing
            else None
        )
        ahead = (
            transactions.list(account, today + timedelta(days=1), last, UPCOMING_LIMIT, 0, q, kind, also, who, tag=tag)
            if is_current and offset == 0
            else []
        )
    except ValueError as e:
        return MonthList(when, is_current, [], 0, None, [], f"Invalid filter: {e}", applied)
    return MonthList(
        when,
        is_current,
        list_rows(chunk, index, transactions),
        total,
        summary_of(everything, index) if everything is not None else None,
        upcoming_items(ahead, index),
        None,
        applied,
    )


# ---- one transaction's details (the sheet) ----------------------------------------------------------------------------


@dataclass
class Line:
    name: str
    amount: Decimal
    posted_on: Date | None


@dataclass
class Details:
    row: TransactionRow
    from_label: str
    to_label: str
    from_lines: list[Line]
    to_lines: list[Line]
    related_to: TransactionRow | None
    related: list[TransactionRow]
    person_id: UUID | None
    person_name: str | None
    loan_like: bool
    with_names: list[str]
    added_by: str | None
    changed_by: str | None


SIDE_LABELS = {"expense": ("Paid from", "Spent on"), "income": ("Earned from", "Paid into"), "transfer": ("From", "To")}


def _assistant(origin: str | None) -> str | None:
    label = origin_label(origin)
    return label.replace(" (AI assistant)", "") if label else None


def transaction_details(
    transaction_id: UUID, transactions: TransactionService, contacts: ContactService, index: AccountIndex
) -> Details | None:
    """What the details sheet shows about one entry; None when it is not the person's."""
    transaction = transactions.read(transaction_id)
    if transaction is None:
        return None
    # An entry made through a person (a loan, a shared bill, a settlement) is looked after on that person's page.
    party = contacts.made_of(transaction_id)
    with_person = contacts.read(party[0].contact_id) if party else None
    purposes = {r.purpose for r in party}
    # A loan, a borrowing or a bill shared with people is edited here too; the rest of what people made is on their page.
    loan_like = bool(party) and (purposes <= {"loan", "borrowing"} or purposes in ({"expense"}, {"income"}))
    names = {c.id: c.name for c in contacts.people()}
    row = to_row(transaction, index)

    def lines(entry: TransactionRead, side: PostingSide) -> list[Line]:
        return [
            Line(index.line_name(p), p.amount, p.posted_on if p.posted_on != entry.date else None)
            for p in entry.postings
            if p.side == side
        ]

    made, changed = transaction.created_via or "", transaction.updated_via or ""
    by_agent = made.startswith("mcp:") or changed.startswith("mcp:")
    from_label, to_label = SIDE_LABELS[row.kind]
    return Details(
        row=row,
        from_label=from_label,
        to_label=to_label,
        from_lines=lines(transaction, PostingSide.CREDIT),
        to_lines=lines(transaction, PostingSide.DEBIT),
        related_to=related_info(transactions, index, transaction.related_id),
        related=[to_row(r, index) for r in transactions.related(transaction_id)],
        person_id=with_person.id if with_person else None,
        person_name=with_person.name if with_person else None,
        loan_like=loan_like,
        with_names=sorted({names[r.contact_id] for r in party if r.contact_id in names}),
        added_by=_assistant(made) if by_agent and made else None,
        changed_by=_assistant(changed) if by_agent and changed and changed != made else None,
    )


@dataclass
class RegisterRow:
    """One entry on an account's or a category's own page (partials/account_entries.html, category_entries.html): what
    it is called, the quiet line under it, the day it posts when that is not its own, and the figure. `inflow` is money
    coming in (green, "+"); `negative` a category's line that went the other way ("−"); `balance` the account's running
    balance (none on a category's page)."""

    id: UUID
    date: Date
    title: str
    sub: str
    posts_on: Date | None
    related: RelatedRef | None
    amount: Decimal
    inflow: bool
    negative: bool
    balance: Decimal | None


def is_inflow(root_name: str, change: Decimal) -> bool:
    """Money coming in, as an account's page marks it (green, "+"): what raises an asset account, and a payment into a
    liability (a card or loan), which lowers what is owed. A charge on a card is plain."""
    return (root_name == "Assets" and change > 0) or (root_name == "Liabilities" and change < 0)


def account_register_row(entry: RegisterEntry, root_name: str) -> RegisterRow:
    """An entry on an account's (or a group's) page. A group's entries name its accounts first, so rows of different
    accounts are told apart."""
    counter = ", ".join(entry.counter_accounts)
    parts = [
        *entry.accounts,
        *([counter] if entry.payee and counter else []),
        *([entry.comment] if entry.comment else []),
    ]
    return RegisterRow(
        id=entry.transaction_id,
        date=entry.date,
        title=entry.payee or counter or ", ".join(entry.accounts),
        sub=" · ".join(parts),
        posts_on=entry.posted_on if entry.posted_on and entry.posted_on != entry.date else None,
        related=entry.related,
        amount=abs(entry.change),
        inflow=is_inflow(root_name, entry.change),
        negative=False,
        balance=entry.balance,
    )


def category_register_row(entry: RegisterEntry, earning: bool) -> RegisterRow:
    """An entry on a category's page: earnings in green with "+", a line that went the other way with "−"."""
    counter = ", ".join(entry.counter_accounts)
    sub = (counter if entry.payee else "") + (" · " if entry.payee and entry.comment else "") + (entry.comment or "")
    return RegisterRow(
        id=entry.transaction_id,
        date=entry.date,
        title=entry.payee or counter,
        sub=sub,
        posts_on=None,
        related=entry.related,
        amount=abs(entry.change),
        inflow=earning and entry.change > 0,
        negative=entry.change < 0,
        balance=None,
    )
