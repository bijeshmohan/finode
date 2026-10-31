import calendar
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated
from urllib.parse import urlencode, urlparse
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import Accounts, Categories, Recurring, Transactions
from ...models.transaction import PostingSide
from ...repositories.transaction import SYSTEM_PAYEES
from ...schemas import AccountRead
from ...schemas.category import CategoryRead
from ...schemas.transaction import (
    PostingCreate,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)
from ...tags import clean_tag
from ...templating import templates
from .accounts import build_tree, category_groups, posting_groups
from .budget import parse_month
from .categories import _month_context
from .utils import UpcomingItem, htmx_error, htmx_redirect, parse_amount, validation_message

router = APIRouter(prefix="/transactions")

PAGE_SIZE = 25

# How many entries dated ahead the transactions page lists under "upcoming".
UPCOMING_LIMIT = 100
KIND_FILTERS = {"expense": "expense", "income": "income", "transfer": "transfer"}


def _more(params: dict, shown: int, total: int, step: int, size: int) -> dict | None:
    """The "Show more" row under a list: where the next chunk comes from and how many entries are still to come."""
    left = total - shown
    if left <= 0:
        return None
    return {
        "url": "/transactions/more?" + urlencode({**params, "offset": shown, "size": size}),
        "n": min(step, left),
        "left": left,
    }


def _applied(filters: dict, index: AccountIndex, rest: dict) -> list[dict]:
    """What is filtered, each with the page's own address without it (the ✕ beside it)."""
    out = []
    for key, label in (("account", "Account"), ("category", "Category"), ("merchant", "Merchant"), ("tag", "Tag")):
        value = filters.get(key)
        if not value:
            continue
        try:
            if key == "tag":
                name = f"#{value}"
            else:
                name = (
                    (index.names.get(UUID(value)) or index.categories.get(UUID(value), "?"))
                    if key != "merchant"
                    else value
                )
        except ValueError:
            name = "?"
        keep = {**rest, **{k: v for k, v in filters.items() if v and k != key}}
        out.append({"key": key, "label": label, "name": name, "remove": "/transactions?" + urlencode(keep)})
    return out


def _summary(found: list, index: AccountIndex) -> dict:
    """How many entries match and, when they all go one way, what they come to."""
    rows = [to_row(t, index) for t in found]
    kinds = {r.kind for r in rows}
    word = {"expense": "spent", "income": "earned"}.get(next(iter(kinds)), "") if len(kinds) == 1 else ""
    return {"count": len(rows), "total": sum((r.amount for r in rows), Decimal(0)) if word else None, "word": word}


def _filter_options(all_accounts, categories: list[CategoryRead], transactions) -> dict:
    """The choices behind the Filter sheet: accounts (assets, liabilities, equity), categories, payees."""
    accounts: list[dict] = []
    for root in build_tree(all_accounts):
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


@dataclass
class TransactionRow:
    transaction: TransactionRead
    debits: list[str]
    credits: list[str]
    amount: Decimal
    kind: str  # expense | income | transfer


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

    def line_name(self, posting) -> str:
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


def _parse_date(value: str) -> date | None:
    value = value.strip()
    return date.fromisoformat(value) if value else None


@router.get("")
def transactions_page(
    request: Request,
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    recurring: Recurring,
    account: str = "",
    category: str = "",
    merchant: str = "",
    tag: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    kind: str = "",
    month: str = "",
):
    try:
        recurring.process_due()  # record what has fallen due; never stop the page from opening
    except Exception:
        recurring.repo.db.rollback()
    all_accounts = accounts.list()
    index = AccountIndex.build(all_accounts, categories.list(include_closed=True))
    kind = KIND_FILTERS.get(kind, "")  # one spelling from here on
    this_month = local_today().replace(day=1)
    when = min(parse_month(month), this_month)  # never a month that has not started
    is_current = when == this_month

    error = None
    rows: list[TransactionRow] = []
    upcoming: list[UpcomingItem] = []
    today = local_today()
    first = last = None
    try:
        first, last = _parse_date(date_from), _parse_date(date_to)
        if first is None and last is None:  # the month pill sets the days; dates in a link still win
            first = when
            # the current month also lists what is dated ahead (the "upcoming" card); a past month ends with its last day
            last = None if is_current else when.replace(day=calendar.monthrange(when.year, when.month)[1])
        # What is dated ahead is not history: it waits in its own row ("N upcoming"), soonest first, on the first page.
        also = UUID(category) if category else None
        who = merchant.strip() or None
        tag = clean_tag(tag)
        # With a filter set the whole match is read (it is one month), so the line above the list can say what it comes to.
        everything = (
            transactions.list(
                UUID(account) if account else None,
                first,
                min(last, today) if last else today,
                None,
                0,
                q,
                KIND_FILTERS.get(kind),
                also,
                who,
                tag=tag or None,
            )
            if (account or category or who or tag)
            else None
        )
        chunk, total = transactions.page(
            0,
            PAGE_SIZE,
            UUID(account) if account else None,
            first,
            min(last, today) if last else today,
            q,
            KIND_FILTERS.get(kind),
            also,
            who,
            tag or None,
        )
        if last is None or last > today:
            ahead = transactions.list(
                UUID(account) if account else None,
                max(first, today + timedelta(days=1)) if first else today + timedelta(days=1),
                last,
                UPCOMING_LIMIT,
                0,
                q,
                KIND_FILTERS.get(kind),
                also,
                who,
                tag=tag or None,
            )
            for t in sorted(ahead, key=lambda t: (t.date, t.created)):
                r = to_row(t, index)
                upcoming.append(
                    UpcomingItem(
                        t.id,
                        t.date,
                        t.payee or ", ".join(r.debits),
                        f"{', '.join(r.credits)} \u2192 {', '.join(r.debits)}" if t.payee else ", ".join(r.credits),
                        r.amount,
                        r.kind == "income",
                    )
                )
    except ValueError as e:
        error = f"Invalid filter: {e}"
        chunk, total = [], 0
        everything = None
    rows = [to_row(t, index) for t in chunk]

    filters = {
        "account": account,
        "category": category,
        "merchant": merchant.strip(),
        "tag": tag,
        "date_from": date_from,
        "date_to": date_to,
    }
    query = {k: v for k, v in filters.items() if v}
    summary = _summary(everything, index) if everything is not None else None
    options = _filter_options(all_accounts, categories.list(include_closed=True), transactions)
    # The month, the filters and the chosen chip also travel with the page links.
    base = {"month": when.strftime("%Y-%m"), **query, **({"q": q.strip()} if q.strip() else {})}
    shown = {**base, **({"kind": kind} if kind else {})}
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "active": "transactions",
            **_month_context(when, is_current),
            "keep": "".join(
                f"&{urlencode({k: v})}"
                for k, v in {
                    **query,
                    **({"kind": kind} if kind else {}),
                    **({"q": q.strip()} if q.strip() else {}),
                }.items()
            ),
            "currency": accounts.currency().code,
            "rows": rows,
            "upcoming": upcoming,
            # What the schedule comes to; left out when something coming in is mixed with what is going out.
            "upcoming_total": sum((r.amount for r in upcoming), 0)
            if upcoming and not any(r.income for r in upcoming)
            else None,
            "error": error,
            "filters": filters,
            "active_filters": len(query),
            "summary": summary,
            "total": total,
            "applied": _applied(
                filters,
                index,
                {
                    "month": when.strftime("%Y-%m"),
                    **({"q": q.strip()} if q.strip() else {}),
                    **({"kind": kind} if kind else {}),
                },
            ),
            "options": options,
            "q": q.strip(),
            "kind": kind,
            "searching": bool(q.strip() or kind or query),
            "roots": build_tree(all_accounts),
            "more": _more(
                {**shown, "scope": "list"},
                len(rows),
                total,
                PAGE_SIZE,
                PAGE_SIZE,
            ),
        },
    )


RELATED_PICKER_LIMIT = 30
HOME_FIRST = 8  # Home starts with this many entries (a day is finished) and "Show more" brings this many each time
HOME_MORE = 10


@router.get("/more")
def more_transactions(
    request: Request,
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    offset: int = 0,
    size: int = PAGE_SIZE,
    scope: str = "list",
    month: str = "",
    account: str = "",
    category: str = "",
    merchant: str = "",
    tag: str = "",
    date_from: str = "",
    date_to: str = "",
    q: str = "",
    kind: str = "",
):
    """The next chunk of the same list (Home's or the Transactions page's), and the row that fetches the one after it."""
    size = min(max(size, 1), 100)
    offset = max(offset, 0)
    today = local_today()
    when = min(parse_month(month), today.replace(day=1))
    try:
        first, last = _parse_date(date_from), _parse_date(date_to)
        if first is None and last is None:
            first, last = when, when.replace(day=calendar.monthrange(when.year, when.month)[1])
        kind = KIND_FILTERS.get(kind, "")
        chunk, total = transactions.page(
            offset,
            size,
            UUID(account) if account else None,
            first,
            min(last, today) if last else today,
            q,
            kind or None,
            UUID(category) if category else None,
            merchant.strip() or None,
            clean_tag(tag) or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    index = AccountIndex.build(accounts.list(), categories.list(include_closed=True))
    params = {
        k: v
        for k, v in {
            "scope": scope,
            "month": when.strftime("%Y-%m"),
            "account": account,
            "category": category,
            "merchant": merchant.strip(),
            "tag": clean_tag(tag),
            "date_from": date_from,
            "date_to": date_to,
            "q": q.strip(),
            "kind": kind,
        }.items()
        if v
    }
    step = HOME_MORE if scope == "home" else PAGE_SIZE
    return templates.TemplateResponse(
        request,
        "partials/transaction_more.html",
        {
            "rows": [to_row(t, index) for t in chunk],
            "more": _more(params, offset + len(chunk), total, step, step),
            "end": {"month": when.strftime("%B"), "total": total},
        },
    )


@router.get("/{transaction_id}/sheet")
def transaction_sheet(
    request: Request,
    transaction_id: UUID,
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    back: str = "",
):
    """The details of one transaction, for the sheet that opens over a list (the edit page has the rest)."""
    transaction = transactions.read(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    index = AccountIndex.build(accounts.list(), categories.list(include_closed=True))
    row = to_row(transaction, index)
    labels = {
        "expense": ("Paid from", "Spent on"),
        "income": ("From", "Received in"),
        "transfer": ("From", "To"),
    }[row.kind]
    return templates.TemplateResponse(
        request,
        "partials/txn_sheet.html",
        {
            "row": row,
            "t": transaction,
            "currency": accounts.currency().code,
            "back": safe_back(back, ""),  # the page to return to after Edit, Repeat or Related (an account's page, say)
            "from_label": labels[0],
            "to_label": labels[1],
            "from_postings": [(index.line_name(p), p) for p in transaction.postings if p.side == PostingSide.CREDIT],
            "to_postings": [(index.line_name(p), p) for p in transaction.postings if p.side == PostingSide.DEBIT],
            "related_to": related_info(transactions, index, transaction.related_id),
            "related": [to_row(r, index) for r in transactions.related(transaction_id)],
        },
    )


def _here(request: Request) -> str:
    """The page an htmx request was made from (path and query), for returning to it after a toast's Undo."""
    url = urlparse(request.headers.get("HX-Current-URL", ""))
    return f"{url.path}?{url.query}" if url.query else url.path


@router.post("/{transaction_id}/delete")
def delete_transaction(
    request: Request,
    transaction_id: UUID,
    transactions: Transactions,
    back: str = "",
    sheet: Annotated[str, Form()] = "",
):
    try:
        transactions.delete(transaction_id)
    except ValueError as e:
        return htmx_error(str(e), "#sheet-error" if sheet else "#page-error")
    # The deletion's own id lets the toast offer Undo (the entry comes back with its old id).
    gone = next((h for h in transactions.deleted() if h.transaction_id == transaction_id), None)
    return htmx_redirect(
        safe_back(back or _here(request)), flash="transaction-deleted", undo=("restore", gone.id) if gone else None
    )


@router.get("/deleted")
def deleted_page(request: Request, accounts: Accounts, transactions: Transactions):
    """Entries that were deleted, newest deletion first, each with a Restore button."""
    entries = transactions.restorable()
    return templates.TemplateResponse(
        request,
        "transactions_deleted.html",
        {"active": "settings", "entries": entries, "currency": accounts.currency().code},
    )


@router.post("/deleted/{history_id}/restore")
def restore_deleted(request: Request, history_id: UUID, transactions: Transactions):
    try:
        transactions.restore(history_id)
    except LookupError:
        return htmx_error("That deleted transaction is not there any more.", "#restore-error", status_code=404)
    except ValueError as e:
        return htmx_error(str(e), "#restore-error")
    return htmx_redirect(safe_back(_here(request), "/transactions/deleted"), flash="transaction-restored")


# Paths that are not pages of the web app.
NOT_PAGES = ("/api", "/mcp", "/static", "/.well-known", "/docs", "/openapi.json")


def safe_back(value: str | None, default: str = "/transactions") -> str:
    """Only follow return paths inside the app (never another host)."""
    if (
        value
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and not value.startswith(NOT_PAGES)
    ):
        return value
    return default


ASSET_LIKE = ("Assets", "Liabilities")


def infer_kind(postings, roots: dict[UUID, str]) -> str:
    """What a set of postings is, for the form's Expense / Income / Transfer buttons: an expense is money from
    assets or liabilities into expenses, income comes from income into them, a transfer is between them;
    anything else (equity, refunds, mixed) is "other", which offers every account."""
    credit = {roots.get(p.account_id) for p in postings if p.side == PostingSide.CREDIT}
    debit = {roots.get(p.account_id) for p in postings if p.side == PostingSide.DEBIT}
    if debit == {"Expenses"} and credit and credit <= set(ASSET_LIKE):
        return "expense"
    if credit == {"Income"} and debit and debit <= set(ASSET_LIKE):
        return "income"
    if credit and debit and credit <= set(ASSET_LIKE) and debit <= set(ASSET_LIKE):
        return "transfer"
    return "other"


def form_context(accounts: Accounts, categories: Categories, **extra) -> dict:
    all_accounts = accounts.list()
    # Accounts and categories an entry being edited already uses stay offered even if they were closed since.
    used = getattr(extra.get("transaction"), "postings", ())
    keep = set(extra.pop("keep", ())) | {p.account_id for p in used}
    keep_categories = {p.category_id for p in used if p.category_id}
    roots = {n.account.id: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
    if "kind" not in extra:
        recorded = getattr(extra.get("transaction"), "postings", None)
        extra["kind"] = infer_kind(recorded, roots) if recorded else "expense"
    return {
        "active": "transactions",
        "hide_fab": True,
        "groups": [
            *posting_groups(build_tree(all_accounts), keep),
            *category_groups(categories.list(include_closed=True), keep_categories),
        ],
        "currency": accounts.currency().code,
        **extra,
    }


def split_postings(
    account: list[str],
    side: list[str],
    amount: list[str],
    category: list[str] | None = None,
    places: Mapping[UUID, UUID] | None = None,
) -> list[PostingCreate]:
    """The form's rows as postings. `category` has one entry per row (blank when the row names none). The form picks an
    expense or an income by its category, so a row whose choice is a key of `places` (category id -> the Expenses or
    Income account it posts to) is a line on that account labelled with the category."""
    places = places or {}
    if not (len(account) == len(side) == len(amount)):
        raise ValueError("every posting needs an account, a side and an amount!")
    if category is not None and len(category) != len(account):
        category = None  # a form from before the Category column: the accounts decide
    postings = []
    for index, (account_id, posting_side, posting_amount) in enumerate(zip(account, side, amount, strict=False)):
        if not account_id and not posting_amount.strip():
            continue  # untouched blank row
        if not account_id:
            raise ValueError("every posting needs an account!")
        label = (category[index] if category else "").strip()
        chosen = UUID(account_id)
        is_category = chosen in places
        postings.append(
            PostingCreate(
                account_id=places[chosen] if is_category else chosen,
                side=PostingSide(posting_side),
                amount=parse_amount(posting_amount),
                category_id=chosen if is_category else (UUID(label) if label else None),
            )
        )
    return postings


def category_places(accounts: Accounts, categories: Categories) -> dict[UUID, UUID]:
    """Where a line labelled with each category posts: the Expenses account for a spending one, Income for an earning one."""
    roots = {a.name: a.id for a in accounts.list() if a.parent_id is None}
    return {c.id: roots["Expenses" if c.kind == "spending" else "Income"] for c in categories.list(include_closed=True)}


def _after_save(back: str, another: str) -> str:
    if another:
        return "/transactions/new" + (f"?{urlencode({'back': back})}" if back else "")
    return safe_back(back)


@dataclass
class PayeeHabit:
    """What the person did the last time they paid someone: who, and which accounts they used."""

    payee: str
    count: int
    from_id: UUID
    to_id: UUID
    kind: str
    from_name: str
    to_name: str
    exact: bool = False


HABIT_HISTORY = 300  # how many recent transactions the suggestions look at


def payee_habits(
    transactions: Transactions, accounts: Accounts, categories: Categories, query: str = "", limit: int = 6
) -> list[PayeeHabit]:
    """Suggestions for the payee field: the people paid most, each with the accounts (or the category) used the last
    time (see `TransactionService.payee_routes`, which the assistants' `payee_defaults` shares)."""
    index = AccountIndex.build(accounts.list(), categories.list(include_closed=True))
    kinds = {c.id: c.kind for c in categories.list(include_closed=True)}
    habits = []
    for route in transactions.payee_routes(query, limit, HABIT_HISTORY):
        habits.append(
            PayeeHabit(
                payee=route.payee,
                count=route.count,
                from_id=route.from_id,
                to_id=route.to_id,
                kind="expense"
                if kinds.get(route.to_id) == "spending"
                else "income"
                if kinds.get(route.from_id) == "earning"
                else "transfer",
                from_name=index.names.get(route.from_id) or index.categories.get(route.from_id, "?"),
                to_name=index.names.get(route.to_id) or index.categories.get(route.to_id, "?"),
                exact=route.exact,
            )
        )
    return habits


@dataclass
class _P:
    """Just enough of a posting for infer_kind."""

    account: UUID
    side: PostingSide


@router.get("/suggest")
def suggest_payees(
    request: Request, accounts: Accounts, categories: Categories, transactions: Transactions, payee: str = ""
):
    """The chips under the payee field: people you pay, with the accounts you used the last time."""
    habits = payee_habits(transactions, accounts, categories, payee)
    return templates.TemplateResponse(request, "partials/payee_chips.html", {"habits": habits})


@router.get("/tag-options")
def tag_options(request: Request, accounts: Accounts, categories: Categories, transactions: Transactions):
    """The tags for the Filter sheet's Tag list, loaded when the list is opened: how many entries carry each, the last
    day, and what they come to when they all go one way (spending or income)."""
    index = AccountIndex.build(accounts.list(), categories.list(include_closed=True))
    stats: dict[str, dict] = {}
    for t in transactions.tagged():
        row = to_row(t, index)
        for name in t.tags:
            s = stats.setdefault(name, {"tag": name, "uses": 0, "last": t.date, "kinds": set(), "sum": Decimal(0)})
            s["uses"] += 1
            s["last"] = max(s["last"], t.date)
            s["kinds"].add(row.kind)
            s["sum"] += row.amount
    items = sorted(stats.values(), key=lambda s: (-s["uses"], s["tag"]))
    for s in items:
        only = next(iter(s["kinds"])) if len(s["kinds"]) == 1 else ""
        s["total"] = s["sum"] if only in ("expense", "income") else None
    return templates.TemplateResponse(request, "partials/tag_options.html", {"items": items})


@router.get("/tag-picker")
def tag_picker(request: Request, transactions: Transactions):
    """The tags in the Add screen's Tags sheet (fetched the first time it is opened); the page marks the chosen ones."""
    return templates.TemplateResponse(request, "partials/tag_picker.html", {"items": transactions.tags()})


def related_info(transactions: Transactions, index: AccountIndex, transaction_id: UUID | None) -> TransactionRow | None:
    """The entry a form or sheet says another is related to, as a row (payee, date, amount); None when there is none."""
    if transaction_id is None:
        return None
    found = transactions.read(transaction_id)
    return to_row(found, index) if found is not None else None


def parse_related(value: str) -> UUID | None:
    try:
        return UUID(value) if value.strip() else None
    except ValueError:
        raise ValueError("the related transaction was not found!") from None


@router.get("/related-picker")
def related_picker(
    request: Request,
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    q: str = "",
    exclude: UUID | None = None,
    results: str = "",
):
    """The sheet that lists earlier entries to relate a new one to: the newest first, narrowed by what is typed."""
    index = AccountIndex.build(accounts.list(), categories.list(include_closed=True))
    found = transactions.list(text=q, limit=RELATED_PICKER_LIMIT + 1, date_to=local_today())
    rows = [to_row(t, index) for t in found if t.id != exclude and t.payee not in SYSTEM_PAYEES][:RELATED_PICKER_LIMIT]
    return templates.TemplateResponse(
        request,
        "partials/related_results.html" if results else "partials/related_picker.html",
        {"rows": rows, "q": q, "exclude": exclude, "currency": accounts.currency().code},
    )


def roots_by_id(accounts: Accounts) -> dict[UUID, str]:
    """Each account's top-level account (Assets, Expenses…), by id."""
    return {n.account.id: r.account.name for r in build_tree(accounts.list()) for n in r.walk()}


def form_rows(
    postings, side: PostingSide, account_id: UUID | None = None, roots: dict[UUID, str] | None = None
) -> list[dict]:
    """The rows of one side of the form: the transaction's own postings, or one blank row (maybe with an account).
    A line on Expenses or Income is picked by its category, which is what the row shows."""
    found = [
        {
            "posting": p,
            "account": p.category_id
            if roots and p.category_id and roots.get(p.account_id) in ("Expenses", "Income")
            else p.account_id,
        }
        for p in postings
        if p.side == side
    ]
    return found or [{"posting": None, "account": account_id}]


@router.get("/new")
def new_transaction_page(
    request: Request,
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    account: UUID | None = None,
    category: UUID | None = None,  # opened from a category's page: the entry starts on that category
    back: str = "",
    repeat: UUID | None = None,  # "add again": a copy of this transaction, dated today
    related: UUID | None = None,  # "related": a blank new entry linked to that transaction
):
    all_accounts = accounts.list()
    if repeat is not None:
        again = transactions.read(repeat)
        if again is None:
            raise HTTPException(status_code=404, detail="transaction not found")
        roots = {n.account.id: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
        return templates.TemplateResponse(
            request,
            "transaction_form.html",
            form_context(
                accounts,
                categories,
                today=local_today().isoformat(),
                transaction=None,
                copy_of=again,
                total=sum((p.amount for p in again.postings if p.side == PostingSide.DEBIT), Decimal(0)),
                new_payee=again.payee or "",
                new_note=again.comment or "",
                from_rows=form_rows(again.postings, PostingSide.CREDIT, roots=roots),
                to_rows=form_rows(again.postings, PostingSide.DEBIT, roots=roots),
                kind=infer_kind(again.postings, roots),
                account=None,
                back=safe_back(back, ""),
                back_url=safe_back(back),
            ),
        )
    linked = None
    if related is not None:
        linked = related_info(
            transactions, AccountIndex.build(all_accounts, categories.list(include_closed=True)), related
        )
        if linked is None:
            raise HTTPException(status_code=404, detail="transaction not found")
    from_id = to_id = None
    roots_of = {n.account.id: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
    kind = {"Income": "income", "Equity": "other"}.get(roots_of.get(account, ""), "expense")
    if account is not None and account in roots_of:
        from_id = account  # the money leaves the account the entry is started from
    chosen = categories.read(category) if category is not None else None
    if chosen is not None:
        if chosen.kind == "spending":
            to_id = chosen.id
        else:
            from_id, kind = chosen.id, "income"
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        form_context(
            accounts,
            categories,
            today=local_today().isoformat(),
            transaction=None,
            from_rows=form_rows([], PostingSide.CREDIT, from_id),
            to_rows=form_rows([], PostingSide.DEBIT, to_id),
            kind=kind,
            related=linked,
            account=account,
            back=safe_back(back, ""),
            back_url=safe_back(back),
        ),
    )


@router.post("/split")
def create_split_transaction(
    transactions: Transactions,
    accounts: Accounts,
    categories: Categories,
    account: Annotated[list[str] | None, Form()] = None,
    side: Annotated[list[str] | None, Form()] = None,
    amount: Annotated[list[str] | None, Form()] = None,
    category: Annotated[list[str] | None, Form()] = None,
    date_: Annotated[str, Form(alias="date")] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
    another: Annotated[str, Form()] = "",
    related: Annotated[str, Form()] = "",
    tags: Annotated[list[str] | None, Form()] = None,
):
    account, side, amount = account or [], side or [], amount or []
    try:
        made = transactions.create(
            TransactionCreate(
                date=date_ or local_today(),
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                postings=split_postings(account, side, amount, category, category_places(accounts, categories)),
                related_id=parse_related(related),
                tags=tags or [],
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(
        _after_save(back, another),
        flash="transaction-saved-next" if another else "transaction-saved",
        undo=("delete", made.id),
    )


@router.get("/{transaction_id}/edit")
def edit_transaction_page(
    request: Request,
    transaction_id: UUID,
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    back: str = "",
):
    transaction = transactions.read(transaction_id)
    if transaction is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    total = sum((p.amount for p in transaction.postings if p.side == PostingSide.DEBIT), Decimal(0))
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        form_context(
            accounts,
            categories,
            editing=True,
            transaction=transaction,
            total=total,
            from_rows=form_rows(transaction.postings, PostingSide.CREDIT, roots=roots_by_id(accounts)),
            to_rows=form_rows(transaction.postings, PostingSide.DEBIT, roots=roots_by_id(accounts)),
            related=related_info(
                transactions,
                AccountIndex.build(accounts.list(), categories.list(include_closed=True)),
                transaction.related_id,
            ),
            account=None,
            back=safe_back(back, ""),
            back_url=safe_back(back),
        ),
    )


def _update(
    transactions: Transactions,
    transaction_id: UUID,
    date_: str,
    payee: str,
    comment: str,
    postings_fn,
    back: str,
    related: str = "",
    tags: list[str] | None = None,
):
    try:
        transactions.update(
            transaction_id,
            TransactionUpdate(
                date=date_ or None,
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                postings=postings_fn(),
                related_id=parse_related(related),
                tags=tags or [],
            ),
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        if "not found" in str(e) and f"'{transaction_id}'" in str(e):
            raise HTTPException(status_code=404, detail="transaction not found") from None
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(safe_back(back), flash="transaction-updated")


@router.post("/{transaction_id}/edit")
def update_transaction(
    transaction_id: UUID,
    transactions: Transactions,
    accounts: Accounts,
    categories: Categories,
    date_: Annotated[str, Form(alias="date")] = "",
    account: Annotated[list[str] | None, Form()] = None,
    side: Annotated[list[str] | None, Form()] = None,
    amount: Annotated[list[str] | None, Form()] = None,
    category: Annotated[list[str] | None, Form()] = None,
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
    related: Annotated[str, Form()] = "",
    tags: Annotated[list[str] | None, Form()] = None,
):
    account, side, amount = account or [], side or [], amount or []
    return _update(
        transactions,
        transaction_id,
        date_,
        payee,
        comment,
        lambda: split_postings(account, side, amount, category, category_places(accounts, categories)),
        back,
        related,
        tags,
    )
