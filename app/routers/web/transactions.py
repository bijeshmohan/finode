from dataclasses import dataclass
import calendar
from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode, urlparse
from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...dependencies import Accounts, Recurring, Transactions
from ...models.transaction import PostingSide
from ...schemas import AccountRead
from ...schemas.transaction import (
    PostingCreate,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)
from ...templating import templates
from .accounts import build_tree, posting_groups
from .budget import parse_month
from .categories import _month_context
from .utils import UpcomingItem, htmx_error, htmx_redirect, parse_amount, validation_message
from ...clock import local_today
from ...services.lock import locked_through


router = APIRouter(prefix="/transactions")

PAGE_SIZE = 25

# How many entries dated ahead the transactions page lists under "upcoming".
UPCOMING_LIMIT = 100
# "spending" and "transfers" are the older spellings of the chips and keep working in saved links.
KIND_FILTERS = {"expense": "expense", "income": "income", "transfer": "transfer", "spending": "expense", "transfers": "transfer"}


def _more(params: dict, shown: int, total: int, step: int, size: int) -> dict | None:
    """The "Show more" row under a list: where the next chunk comes from and how many entries are still to come."""
    left = total - shown
    if left <= 0:
        return None
    return {"url": "/transactions/more?" + urlencode({**params, "offset": shown, "size": size}), "n": min(step, left), "left": left}


def _applied(filters: dict, index: "AccountIndex", rest: dict) -> list[dict]:
    """What is filtered, each with the page's own address without it (the ✕ beside it)."""
    out = []
    for key, label in (("account", "Account"), ("category", "Category"), ("merchant", "Merchant")):
        value = filters.get(key)
        if not value:
            continue
        try:
            name = index.names.get(UUID(value), "?") if key != "merchant" else value
        except ValueError:
            name = "?"
        keep = {**rest, **{k: v for k, v in filters.items() if v and k != key}}
        out.append({"key": key, "label": label, "name": name, "remove": "/transactions?" + urlencode(keep)})
    return out


def _summary(found: list, index: "AccountIndex") -> dict:
    """How many entries match and, when they all go one way, what they come to."""
    rows = [to_row(t, index) for t in found]
    kinds = {r.kind for r in rows}
    word = {"expense": "spent", "income": "earned"}.get(next(iter(kinds)), "") if len(kinds) == 1 else ""
    return {"count": len(rows), "total": sum((r.amount for r in rows), Decimal(0)) if word else None, "word": word}


def _filter_options(all_accounts, transactions) -> dict:
    """The choices behind the Filter sheet: accounts (assets, liabilities, equity), categories (expenses, income), payees."""
    accounts, categories = [], []
    for root in build_tree(all_accounts):
        target = categories if root.account.name in ("Expenses", "Income") else accounts
        parents: dict[int, str] = {}
        for node in root.walk():
            parents[node.depth] = node.account.name
            if node.depth == 0:
                continue
            sub = parents.get(node.depth - 1) if node.depth > 1 else ""
            target.append({"aid": str(node.account.aid), "name": node.account.name, "sub": sub})
    return {"accounts": accounts, "categories": categories, "merchants": [name for name, _ in transactions.payees()]}


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

    @classmethod
    def build(cls, accounts: list[AccountRead]) -> "AccountIndex":
        names = {a.aid: a.name for a in accounts}
        roots = {
            node.account.aid: root.account.name
            for root in build_tree(accounts)
            for node in root.walk()
        }
        return cls(names, roots)


def to_row(transaction: TransactionRead, index: AccountIndex) -> TransactionRow:
    def side_names(side: PostingSide) -> list[str]:
        found: list[str] = []
        for posting in transaction.postings:
            name = index.names.get(posting.account, "?")
            if posting.side == side and name not in found:
                found.append(name)
        return found

    def touches(root: str, side: PostingSide) -> bool:
        return any(
            p.side == side and index.roots.get(p.account) == root for p in transaction.postings
        )

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
    transactions: Transactions,
    recurring: Recurring,
    account: str = "",
    category: str = "",
    merchant: str = "",
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
    index = AccountIndex.build(all_accounts)
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
        # With a filter set the whole match is read (it is one month), so the line above the list can say what it comes to.
        everything = transactions.list(
            UUID(account) if account else None, first, min(last, today) if last else today, None, 0, q, KIND_FILTERS.get(kind), also, who,
        ) if (account or category or who) else None
        chunk, total = transactions.page(
            0, PAGE_SIZE, UUID(account) if account else None, first, min(last, today) if last else today, q, KIND_FILTERS.get(kind), also, who,
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
            )
            for t in sorted(ahead, key=lambda t: (t.date, t.created)):
                r = to_row(t, index)
                upcoming.append(UpcomingItem(
                    t.tid, t.date, t.payee or ", ".join(r.debits), f"{', '.join(r.credits)} \u2192 {', '.join(r.debits)}" if t.payee else ", ".join(r.credits),
                    r.amount, r.kind == "income",
                ))
    except ValueError as e:
        error = f"Invalid filter: {e}"
        chunk, total = [], 0
        everything = None
    rows = [to_row(t, index) for t in chunk]

    filters = {"account": account, "category": category, "merchant": merchant.strip(), "date_from": date_from, "date_to": date_to}
    query = {k: v for k, v in filters.items() if v}
    summary = _summary(everything, index) if everything is not None else None
    options = _filter_options(all_accounts, transactions)
    # The month, the filters and the chosen chip also travel with the page links.
    base = {"month": when.strftime("%Y-%m"), **query, **({"q": q.strip()} if q.strip() else {})}
    shown = {**base, **({"kind": kind} if kind else {})}
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "active": "transactions",
            **_month_context(when, is_current),
            "keep": "".join(f"&{urlencode({k: v})}" for k, v in {**query, **({"kind": kind} if kind else {}), **({"q": q.strip()} if q.strip() else {})}.items()),
            "currency": accounts.currency().code,
            "rows": rows,
            "upcoming": upcoming,
            # What the schedule comes to; left out when something coming in is mixed with what is going out.
            "upcoming_total": sum((r.amount for r in upcoming), 0) if upcoming and not any(r.income for r in upcoming) else None,
            "error": error,
            "filters": filters,
            "active_filters": len(query),
            "summary": summary,
            "applied": _applied(filters, index, {"month": when.strftime("%Y-%m"), **({"q": q.strip()} if q.strip() else {}), **({"kind": kind} if kind else {})}),
            "options": options,
            "q": q.strip(),
            "kind": kind,
            "searching": bool(q.strip() or kind or query),
            "roots": build_tree(all_accounts),
            "more": _more(
                {**shown, "scope": "list"}, len(rows), total, PAGE_SIZE, PAGE_SIZE,
            ),
        },
    )


HOME_FIRST = 8  # Home starts with this many entries (a day is finished) and "Show more" brings this many each time
HOME_MORE = 10


@router.get("/more")
def more_transactions(
    request: Request,
    accounts: Accounts,
    transactions: Transactions,
    offset: int = 0,
    size: int = PAGE_SIZE,
    scope: str = "list",
    month: str = "",
    account: str = "",
    category: str = "",
    merchant: str = "",
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
            offset, size, UUID(account) if account else None, first, min(last, today) if last else today, q, kind or None,
            UUID(category) if category else None, merchant.strip() or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    index = AccountIndex.build(accounts.list())
    params = {k: v for k, v in {
        "scope": scope, "month": when.strftime("%Y-%m"), "account": account, "category": category, "merchant": merchant.strip(),
        "date_from": date_from, "date_to": date_to, "q": q.strip(), "kind": kind,
    }.items() if v}
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


@router.get("/{tid}/sheet")
def transaction_sheet(request: Request, tid: UUID, accounts: Accounts, transactions: Transactions):
    """The details of one transaction, for the sheet that opens over a list (the edit page has the rest)."""
    transaction = transactions.read(tid)
    if transaction is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    row = to_row(transaction, AccountIndex.build(accounts.list()))
    names = AccountIndex.build(accounts.list()).names
    lock = locked_through(transactions.tr.db, transactions.tr.uid)
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
            "from_label": labels[0],
            "to_label": labels[1],
            "from_postings": [(names.get(p.account, "?"), p) for p in transaction.postings if p.side == PostingSide.CREDIT],
            "to_postings": [(names.get(p.account, "?"), p) for p in transaction.postings if p.side == PostingSide.DEBIT],
            "locked_by": lock if lock is not None and transaction.date <= lock else None,
        },
    )


def _here(request: Request) -> str:
    """The page an htmx request was made from (path and query), for returning to it after a toast's Undo."""
    url = urlparse(request.headers.get("HX-Current-URL", ""))
    return f"{url.path}?{url.query}" if url.query else url.path


@router.post("/{tid}/delete")
def delete_transaction(request: Request, tid: UUID, transactions: Transactions, back: str = "", sheet: Annotated[str, Form()] = ""):
    try:
        transactions.delete(tid)
    except ValueError as e:
        return htmx_error(str(e), "#sheet-error" if sheet else "#page-error")
    # The deletion's own id lets the toast offer Undo (the entry comes back with its old id).
    gone = next((h for h in transactions.deleted() if h.transaction == tid), None)
    return htmx_redirect(
        safe_back(back or _here(request)), flash="transaction-deleted", undo=("restore", gone.hid) if gone else None
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


@router.post("/deleted/{hid}/restore")
def restore_deleted(request: Request, hid: UUID, transactions: Transactions):
    try:
        transactions.restore(hid)
    except LookupError:
        return htmx_error("That deleted transaction is not there any more.", "#restore-error", status_code=404)
    except ValueError as e:
        return htmx_error(str(e), "#restore-error")
    return htmx_redirect(safe_back(_here(request), "/transactions/deleted"), flash="transaction-restored")


# Paths that are not pages of the web app.
NOT_PAGES = ("/api", "/mcp", "/static", "/.well-known", "/docs", "/openapi.json")


def safe_back(value: str | None, default: str = "/transactions") -> str:
    """Only follow return paths inside the app (never another host)."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value and not value.startswith(NOT_PAGES):
        return value
    return default


ASSET_LIKE = ("Assets", "Liabilities")


def infer_kind(postings, roots: dict[UUID, str]) -> str:
    """What a set of postings is, for the form's Expense / Income / Transfer buttons: an expense is money from
    assets or liabilities into expenses, income comes from income into them, a transfer is between them;
    anything else (equity, refunds, mixed) is "other", which offers every account."""
    credit = {roots.get(p.account) for p in postings if p.side == PostingSide.CREDIT}
    debit = {roots.get(p.account) for p in postings if p.side == PostingSide.DEBIT}
    if debit == {"Expenses"} and credit and credit <= set(ASSET_LIKE):
        return "expense"
    if credit == {"Income"} and debit and debit <= set(ASSET_LIKE):
        return "income"
    if credit and debit and credit <= set(ASSET_LIKE) and debit <= set(ASSET_LIKE):
        return "transfer"
    return "other"


def form_context(accounts: Accounts, **extra) -> dict:
    all_accounts = accounts.list()
    # Accounts an entry being edited already uses stay offered even if they were closed since.
    keep = set(extra.pop("keep", ())) | {p.account for p in getattr(extra.get("transaction"), "postings", ())}
    roots = {n.account.aid: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
    if "kind" not in extra:
        recorded = getattr(extra.get("transaction"), "postings", None)
        extra["kind"] = infer_kind(recorded, roots) if recorded else "expense"
    return {
        "active": "transactions",
        "hide_fab": True,
        "groups": posting_groups(build_tree(all_accounts), keep),
        "currency": accounts.currency().code,
        **extra,
    }


def split_postings(account: list[str], side: list[str], amount: list[str]) -> list[PostingCreate]:
    if not (len(account) == len(side) == len(amount)):
        raise ValueError("every posting needs an account, a side and an amount!")
    postings = []
    for account_id, posting_side, posting_amount in zip(account, side, amount):
        if not account_id and not posting_amount.strip():
            continue  # untouched blank row
        if not account_id:
            raise ValueError("every posting needs an account!")
        postings.append(
            PostingCreate(
                account=UUID(account_id),
                side=PostingSide(posting_side),
                amount=parse_amount(posting_amount),
            )
        )
    return postings


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
    amount: str = ""  # what the last one came to, for the "as last time" chip


HABIT_HISTORY = 300  # how many recent transactions the suggestions look at


def payee_habits(transactions: Transactions, accounts: Accounts, query: str = "", limit: int = 6) -> tuple[list[PayeeHabit], UUID | None]:
    """Suggestions for the payee field, and the account most often paid from lately.

    Only entries with one account on each side count (a split has no single route to repeat), and only accounts
    that can still be used. Payees you pay often come first; typing narrows them to those starting with, then
    containing, what was typed.
    """
    all_accounts = accounts.list()
    index = AccountIndex.build(all_accounts)
    usable = {a.aid for a in all_accounts if a.parent_id is not None and a.closed_on is None}
    wanted = query.strip().lower()
    seen: dict[str, dict] = {}
    from_counts: dict[UUID, int] = {}
    for position, t in enumerate(transactions.list(limit=HABIT_HISTORY)):
        credits = [p for p in t.postings if p.side == PostingSide.CREDIT]
        debits = [p for p in t.postings if p.side == PostingSide.DEBIT]
        simple = (
            len(credits) == 1 and len(debits) == 1
            and credits[0].account in usable and debits[0].account in usable
            and "Equity" not in (index.roots.get(credits[0].account), index.roots.get(debits[0].account))  # opening balances are not a payee
        )
        if simple and position < 40 and index.roots.get(credits[0].account) in ASSET_LIKE:
            from_counts[credits[0].account] = from_counts.get(credits[0].account, 0) + 1
        payee = (t.payee or "").strip()
        if not payee or not simple:
            continue
        entry = seen.setdefault(payee.lower(), {"payee": payee, "count": 0, "route": (credits[0].account, debits[0].account), "order": position, "amount": format(debits[0].amount.normalize(), "f")})
        entry["count"] += 1  # the first one seen is the newest: its route is the one repeated
    habits = []
    for key, entry in seen.items():
        if wanted and wanted not in key:
            continue
        from_id, to_id = entry["route"]
        roots = index.roots
        habits.append((
            0 if wanted and key == wanted else 1 if key.startswith(wanted) else 2, -entry["count"], entry["order"],
            PayeeHabit(
                payee=entry["payee"], count=entry["count"], from_id=from_id, to_id=to_id,
                kind=infer_kind([_P(from_id, PostingSide.CREDIT), _P(to_id, PostingSide.DEBIT)], roots),
                from_name=index.names.get(from_id, "?"), to_name=index.names.get(to_id, "?"), exact=bool(wanted) and key == wanted,
                amount=entry["amount"],
            ),
        ))
    habits.sort(key=lambda h: h[:3])
    favourite = max(from_counts, key=from_counts.get) if from_counts else None
    return [h[3] for h in habits[:limit]], favourite


@dataclass
class _P:
    """Just enough of a posting for infer_kind."""

    account: UUID
    side: PostingSide


def split_quick_entry(text: str) -> tuple[str, str]:
    """What was typed in the quick-add bar: "250 swiggy" -> ("250", "swiggy"); "swiggy 250" works too."""
    import re

    text = (text or "").strip()
    found = re.match(r"^(\d[\d,]*(?:\.\d+)?)\s*(.*)$", text) or re.match(r"^(.*?)\s+(\d[\d,]*(?:\.\d+)?)$", text)
    if not found:
        return "", text
    first, second = found.groups()
    number, words = (first, second) if first[:1].isdigit() else (second, first)
    return number.replace(",", ""), words.strip()


@router.get("/suggest")
def suggest_payees(request: Request, accounts: Accounts, transactions: Transactions, payee: str = ""):
    """The chips under the payee field: people you pay, with the accounts you used the last time."""
    habits, _ = payee_habits(transactions, accounts, payee)
    return templates.TemplateResponse(request, "partials/payee_chips.html", {"habits": habits})


def form_rows(postings, side: PostingSide, account_id: UUID | None = None) -> list[dict]:
    """The rows of one side of the form: the transaction's own postings, or one blank row (maybe with an account)."""
    found = [{"posting": p, "account": p.account} for p in postings if p.side == side]
    return found or [{"posting": None, "account": account_id}]


@router.get("/new")
def new_transaction_page(
    request: Request,
    accounts: Accounts,
    transactions: Transactions,
    account: UUID | None = None,
    back: str = "",
    q: str = "",  # what was typed in the quick-add bar: "250 swiggy"
    repeat: UUID | None = None,  # "add again": a copy of this transaction, dated today
    mode: str = "",  # old links; the form is one page now
):
    all_accounts = accounts.list()
    if repeat is not None:
        again = transactions.read(repeat)
        if again is None:
            raise HTTPException(status_code=404, detail="transaction not found")
        roots = {n.account.aid: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
        return templates.TemplateResponse(
            request,
            "transaction_form.html",
            form_context(
                accounts,
                today=local_today().isoformat(),
                transaction=None,
                copy_of=again,
                total=sum((p.amount for p in again.postings if p.side == PostingSide.DEBIT), Decimal(0)),
                new_payee=again.payee or "",
                new_note=again.comment or "",
                from_rows=form_rows(again.postings, PostingSide.CREDIT),
                to_rows=form_rows(again.postings, PostingSide.DEBIT),
                kind=infer_kind(again.postings, roots),
                account=None,
                back=safe_back(back, ""),
                back_url=safe_back(back),
            ),
        )
    from_id = to_id = None
    roots_of = {n.account.aid: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
    amount_text, payee_text = split_quick_entry(q)
    kind = {"Income": "income", "Equity": "other"}.get(roots_of.get(account), "expense")
    habits, favourite = payee_habits(transactions, accounts, payee_text) if (payee_text or account is None) else ([], None)
    if account is not None:
        # From an expense category the money arrives there; from anything else it leaves.
        if roots_of.get(account) == "Expenses":
            to_id = account
        elif account in roots_of:
            from_id = account
    else:
        match = next((h for h in habits if h.exact), None)
        if match is not None:  # a payee you have paid before: the same accounts as last time
            from_id, to_id, kind = match.from_id, match.to_id, match.kind
            payee_text = match.payee  # spelled the way you wrote it before
        elif favourite is not None:
            from_id = favourite  # otherwise the account you paid from most lately
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        form_context(
            accounts,
            today=local_today().isoformat(),
            transaction=None,
            total=amount_text,
            new_payee=payee_text,
            from_rows=form_rows([], PostingSide.CREDIT, from_id),
            to_rows=form_rows([], PostingSide.DEBIT, to_id),
            kind=kind,
            account=account,
            back=safe_back(back, ""),
            back_url=safe_back(back),
        ),
    )


@router.post("/split")
def create_split_transaction(
    transactions: Transactions,
    account: Annotated[list[str], Form()] = [],
    side: Annotated[list[str], Form()] = [],
    amount: Annotated[list[str], Form()] = [],
    date_: Annotated[str, Form(alias="date")] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
    another: Annotated[str, Form()] = "",
):
    try:
        made = transactions.create(
            TransactionCreate(
                date=date_ or local_today(),
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                postings=split_postings(account, side, amount),
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(
        _after_save(back, another),
        flash="transaction-saved-next" if another else "transaction-saved",
        undo=("delete", made.tid),
    )


@router.get("/{tid}/edit")
def edit_transaction_page(
    request: Request,
    tid: UUID,
    accounts: Accounts,
    transactions: Transactions,
    back: str = "",
    mode: str = "",  # old links; the form is one page now
):
    transaction = transactions.read(tid)
    if transaction is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    total = sum((p.amount for p in transaction.postings if p.side == PostingSide.DEBIT), Decimal(0))
    lock = locked_through(transactions.tr.db, transactions.tr.uid)
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        form_context(
            accounts,
            editing=True,
            locked_by=lock if lock is not None and transaction.date <= lock else None,
            transaction=transaction,
            total=total,
            from_rows=form_rows(transaction.postings, PostingSide.CREDIT),
            to_rows=form_rows(transaction.postings, PostingSide.DEBIT),
            account=None,
            back=safe_back(back, ""),
            back_url=safe_back(back),
        ),
    )


def _update(transactions: Transactions, tid: UUID, date_: str, payee: str, comment: str, postings_fn, back: str):
    try:
        transactions.update(
            tid,
            TransactionUpdate(
                date=date_ or None,
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                postings=postings_fn(),
            ),
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        if "not found" in str(e) and f"'{tid}'" in str(e):
            raise HTTPException(status_code=404, detail="transaction not found")
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(safe_back(back), flash="transaction-updated")


@router.post("/{tid}/edit")
def update_transaction(
    tid: UUID,
    transactions: Transactions,
    date_: Annotated[str, Form(alias="date")] = "",
    account: Annotated[list[str], Form()] = [],
    side: Annotated[list[str], Form()] = [],
    amount: Annotated[list[str], Form()] = [],
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
):
    return _update(
        transactions,
        tid,
        date_,
        payee,
        comment,
        lambda: split_postings(account, side, amount),
        back,
    )
