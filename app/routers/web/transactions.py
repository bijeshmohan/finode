"""The Transactions page, an entry's sheet and the Add / Edit screen (expense, income, transfer, split, people)."""

import calendar
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated
from urllib.parse import urlencode, urlparse
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import (
    Accounts,
    Categories,
    Contacts,
    Entries,
    Recurring,
    SharedExpenses,
    SharedIncomes,
    Transactions,
    Transfers,
)
from ...models.transaction import PostingSide
from ...repositories.transaction import SYSTEM_PAYEES
from ...schemas.entry import EntryForm, EntryRow
from ...schemas.transaction import (
    PostingCreate,
)
from ...services import payee_suggestions
from ...services.account_tree import build_tree, without_contacts
from ...services.entry import infer_kind, postings_of
from ...services.entry_form import edit_start, new_start
from ...services.entry_share import expense_start, income_start
from ...services.pickers import category_groups, people_group, posting_groups
from ...services.transaction_rows import (
    HOME_MORE,
    KIND_FILTERS,
    PAGE_SIZE,
    UPCOMING_LIMIT,
    AccountIndex,
    TransactionRow,
    UpcomingItem,
    filter_options,
    list_rows,
    summary_of,
    to_row,
    transaction_details,
    upcoming_items,
)
from ...tags import clean_tag
from ...templating import templates
from .budget import parse_month
from .categories import _month_context, category_tree
from .people import expense_entry, income_entry
from .utils import htmx_error, htmx_redirect, parse_amount, validation_message

router = APIRouter(prefix="/transactions")


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
    recurring.catch_up()  # record what has fallen due; it never stops the page from opening
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
            upcoming = upcoming_items(ahead, index)
    except ValueError as e:
        error = f"Invalid filter: {e}"
        chunk, total = [], 0
        everything = None
    rows = list_rows(chunk, index, transactions)

    filters = {
        "account": account,
        "category": category,
        "merchant": merchant.strip(),
        "tag": tag,
        "date_from": date_from,
        "date_to": date_to,
    }
    query = {k: v for k, v in filters.items() if v}
    summary = summary_of(everything, index) if everything is not None else None
    options = filter_options(all_accounts, categories.list(include_closed=True), transactions)
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
            "roots": without_contacts(build_tree(all_accounts)),
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
            "rows": list_rows(chunk, index, transactions),
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
    contacts: Contacts,
    back: str = "",
):
    """The details of one transaction, for the sheet that opens over a list (the edit page has the rest). Edit, Repeat and
    Related bring you back to the page the sheet was opened on, filters and month included."""
    index = AccountIndex.build(accounts.list(), categories.list(include_closed=True))
    found = transaction_details(transaction_id, transactions, contacts, index)
    if found is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return templates.TemplateResponse(
        request,
        "partials/txn_sheet.html",
        {
            "row": found.row,
            "t": found.row.transaction,
            "currency": accounts.currency().code,
            "back": safe_back(back or _here(request), ""),  # where to return after Edit, Repeat or Related
            "from_label": found.from_label,
            "to_label": found.to_label,
            "from_postings": [(line.name, line) for line in found.from_lines],
            "to_postings": [(line.name, line) for line in found.to_lines],
            "related_to": found.related_to,
            "related": found.related,
            "with_person": {"id": found.person_id, "name": found.person_name} if found.person_id else None,
            "loan_like": found.loan_like,
            "with_names": found.with_names,
        },
    )


def _here(request: Request) -> str:
    """The page an htmx request was made from (path and query), for returning to it."""
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
    return htmx_redirect(safe_back(back or _here(request)), flash="transaction-deleted")


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


async def _shared_entry(
    request: Request, contacts: Contacts, kind: str, comment: str, tags: list[str] | None, related: str
) -> EntryForm:
    """The Split part of the form: a bill (or, on an income, the income) shared with people."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    read = income_entry if kind == "income" else expense_entry
    return read(form, contacts.people()).model_copy(
        update={"comment": comment.strip() or None, "tags": tags or [], "related_id": parse_related(related)}
    )


def form_context(accounts: Accounts, categories: Categories, contacts: Contacts | None = None, **extra) -> dict:
    all_accounts = accounts.list()
    people = [c for c in contacts.people() if c.archived_at is None] if contacts and contacts.has_people() else []
    # Accounts and categories an entry being edited already uses stay offered even if they were closed since.
    used = getattr(extra.get("transaction"), "postings", ())
    keep = set(extra.pop("keep", ())) | {p.account_id for p in used}
    keep_categories = {p.category_id for p in used if p.category_id}
    keep_people = set(extra.pop("keep_people", ()))
    roots = {n.account.id: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
    if "kind" not in extra:
        recorded = getattr(extra.get("transaction"), "postings", None)
        extra["kind"] = infer_kind(recorded, roots) if recorded else "expense"
    return {
        "active": "transactions",
        "hide_fab": True,
        "groups": [
            *posting_groups(build_tree(all_accounts), keep),
            *people_group(contacts, keep_people),
            *category_groups(categories.list(include_closed=True), keep_categories),
        ],
        "currency": accounts.currency().code,
        "people": people,
        "money_groups": [g for g in posting_groups(build_tree(all_accounts)) if g[0] in ("Assets", "Liabilities")],
        "spending": category_tree(categories, "spending"),
        "earning": category_tree(categories, "earning"),
        "mode": "simple",
        "ed": expense_start(None),
        "ei": income_start(None),
        **extra,
    }


def form_entry_rows(
    account: list[str],
    side: list[str],
    amount: list[str],
    category: list[str] | None = None,
    posted_on: list[str] | None = None,
) -> list[EntryRow]:
    """The form's rows as the person chose them. `category` and `posted_on` have one entry per row (blank when the row
    names none); untouched blank rows are left out."""
    if not (len(account) == len(side) == len(amount)):
        raise ValueError("every posting needs an account, a side and an amount!")
    if category is not None and len(category) != len(account):
        category = None  # a form from before the Category column: the accounts decide
    if posted_on is not None and len(posted_on) != len(account):
        posted_on = None  # a form from before the posting dates: every line is on the entry's own date
    rows = []
    for index, (choice, row_side, row_amount) in enumerate(zip(account, side, amount, strict=False)):
        if not choice and not row_amount.strip():
            continue  # untouched blank row
        if not choice:
            raise ValueError("every posting needs an account!")
        label = (category[index] if category else "").strip()
        posted = (posted_on[index] if posted_on else "").strip()
        rows.append(
            EntryRow(
                choice=UUID(choice),
                side=PostingSide(row_side),
                amount=parse_amount(row_amount),
                category_id=UUID(label) if label else None,
                posted_on=date.fromisoformat(posted) if posted else None,
            )
        )
    return rows


def split_postings(
    account: list[str],
    side: list[str],
    amount: list[str],
    category: list[str] | None = None,
    places: Mapping[UUID, UUID] | None = None,
    posted_on: list[str] | None = None,
) -> list[PostingCreate]:
    """The form's rows as postings (the recurring form's too): a category posts on Expenses or Income (entry.postings_of)."""
    return postings_of(form_entry_rows(account, side, amount, category, posted_on), places or {})


def entry_form(
    kind: str,
    date_: str,
    payee: str,
    comment: str,
    tags: list[str] | None,
    related: str,
    payee_contact: str,
    rows: list[EntryRow],
) -> EntryForm:
    """What the web form says, as the entry service takes it."""
    try:
        contact = UUID(payee_contact) if payee_contact.strip() else None
    except ValueError:
        raise ValueError("choose the person from the list!") from None
    return EntryForm(
        kind=kind if kind in ("expense", "income", "transfer") else "other",
        date=date.fromisoformat(date_) if date_ else None,
        payee=payee,
        comment=comment,
        tags=tags or [],
        related_id=parse_related(related),
        payee_contact=contact,
        rows=rows,
    )


def category_places(accounts: Accounts, categories: Categories) -> dict[UUID, UUID]:
    """Where a line labelled with each category posts: the Expenses account for a spending one, Income for an earning one."""
    roots = {a.name: a.id for a in accounts.list() if a.parent_id is None}
    return {c.id: roots["Expenses" if c.kind == "spending" else "Income"] for c in categories.list(include_closed=True)}


@router.get("/suggest")
def suggest_payees(request: Request, transactions: Transactions, contacts: Contacts, payee: str = "", only: str = ""):
    """The chips under the payee field (see services/payee_suggestions.py)."""
    found = payee_suggestions.suggest(transactions, contacts, payee, only)
    people = [(p.id, p.name) for p in found.people]
    return templates.TemplateResponse(request, "partials/payee_chips.html", {"names": found.names, "people": people})


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


@router.get("/new")
def new_transaction_page(
    request: Request,
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    contacts: Contacts,
    account: UUID | None = None,
    category: UUID | None = None,  # opened from a category's page: the entry starts on that category
    back: str = "",
    repeat: UUID | None = None,  # "add again": a copy of this transaction, dated today
    related: UUID | None = None,  # "related": a blank new entry linked to that transaction
    pay: UUID
    | None = None,  # "pay bill": a payment into this card or loan, for `amount`; the account paid from is left to choose
    amount: str = "",
    mode: str = "",  # "split": open on the Split tab (from a person's page)
    with_person: Annotated[UUID | None, Query(alias="with")] = None,  # the person ticked on that tab
    move: str = "",  # "lend", "borrow" or "settle": a transfer with that person, from their page
):
    try:
        start = new_start(
            accounts,
            categories,
            transactions,
            contacts,
            account,
            category,
            repeat,
            related,
            pay,
            amount,
            move,
            with_person,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    split = mode == "split" and repeat is None
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        form_context(
            accounts,
            categories,
            contacts,
            today=local_today().isoformat(),
            transaction=None,
            copy_of=start.copy_of,
            new_payee=start.payee,
            new_note=start.comment,
            from_rows=start.from_rows,
            to_rows=start.to_rows,
            mode="split" if split else "simple",
            ed=expense_start(None, with_person if split and not move else None),
            kind="expense" if split else start.kind,
            related=start.related,
            total=start.total,
            account=account if repeat is None else None,
            back=safe_back(back, ""),
            back_url=safe_back(back),
        ),
    )


@router.post("/split")
async def create_split_transaction(
    request: Request,
    transactions: Transactions,
    entries: Entries,
    contacts: Contacts,
    account: Annotated[list[str] | None, Form()] = None,
    side: Annotated[list[str] | None, Form()] = None,
    amount: Annotated[list[str] | None, Form()] = None,
    category: Annotated[list[str] | None, Form()] = None,
    posted_on: Annotated[list[str] | None, Form()] = None,
    date_: Annotated[str, Form(alias="date")] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
    related: Annotated[str, Form()] = "",
    tags: Annotated[list[str] | None, Form()] = None,
    mode: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "",
    payee_contact: Annotated[str, Form()] = "",
):
    account, side, amount = account or [], side or [], amount or []
    try:
        if mode == "split" and kind != "transfer":
            # Split: a bill or an income shared with people, as the form lists it.
            shared = entries.create(await _shared_entry(request, contacts, kind, comment, tags, related))
            return htmx_redirect(safe_back(back), flash=shared.recorded)
        saved = entries.create(
            entry_form(
                kind,
                date_,
                payee,
                comment,
                tags,
                related,
                payee_contact,
                form_entry_rows(account, side, amount, category, posted_on),
            )
        )
        if saved.recorded == "transfer":
            return htmx_redirect(safe_back(back), flash="transfer-recorded")
    except ValidationError as e:
        transactions.discard()
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        transactions.discard()
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(safe_back(back), flash="transaction-saved")


@router.get("/{transaction_id}/edit")
def edit_transaction_page(
    request: Request,
    transaction_id: UUID,
    accounts: Accounts,
    categories: Categories,
    transactions: Transactions,
    contacts: Contacts,
    transfers: Transfers,
    expenses: SharedExpenses,
    incomes: SharedIncomes,
    back: str = "",
):
    try:
        start = edit_start(transaction_id, accounts, categories, transactions, contacts, transfers, expenses, incomes)
    except LookupError:
        raise HTTPException(status_code=404, detail="transaction not found") from None
    if start.person_page is not None:
        return RedirectResponse(f"/people/{start.person_page}", status_code=303)
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        form_context(
            accounts,
            categories,
            contacts,
            keep_people=start.keep_people,
            payee_person=start.payee_person,
            editing=True,
            transaction=start.transaction,
            total=start.total,
            from_rows=start.from_rows,
            to_rows=start.to_rows,
            mode=start.mode,
            ed=expense_start(start.bill),
            ei=income_start(start.shared_income),
            **({"kind": start.kind} if start.mode == "split" else {}),
            related=start.related,
            account=None,
            back=safe_back(back, ""),
            back_url=safe_back(back),
        ),
    )


@router.post("/{transaction_id}/edit")
async def update_transaction(
    request: Request,
    transaction_id: UUID,
    transactions: Transactions,
    entries: Entries,
    contacts: Contacts,
    date_: Annotated[str, Form(alias="date")] = "",
    account: Annotated[list[str] | None, Form()] = None,
    side: Annotated[list[str] | None, Form()] = None,
    amount: Annotated[list[str] | None, Form()] = None,
    category: Annotated[list[str] | None, Form()] = None,
    posted_on: Annotated[list[str] | None, Form()] = None,
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
    related: Annotated[str, Form()] = "",
    tags: Annotated[list[str] | None, Form()] = None,
    mode: Annotated[str, Form()] = "",
    kind: Annotated[str, Form()] = "",
    payee_contact: Annotated[str, Form()] = "",
):
    account, side, amount = account or [], side or [], amount or []
    try:
        if mode == "split" and kind != "transfer":
            # Split: the entry becomes (or stays) a bill or an income shared with people, in place.
            entries.update(transaction_id, await _shared_entry(request, contacts, kind, comment, tags, related))
            return htmx_redirect(safe_back(back), flash="transaction-updated")
        entries.update(
            transaction_id,
            entry_form(
                kind,
                date_,
                payee,
                comment,
                tags,
                related,
                payee_contact,
                form_entry_rows(account, side, amount, category, posted_on),
            ),
        )
        return htmx_redirect(safe_back(back), flash="transaction-updated")
    except LookupError:
        raise HTTPException(status_code=404, detail="transaction not found") from None
    except ValidationError as e:
        transactions.discard()
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        transactions.discard()
        if "not found" in str(e) and f"'{transaction_id}'" in str(e):
            raise HTTPException(status_code=404, detail="transaction not found") from None
        return htmx_error(str(e), "#form-error")
    except HTTPException:
        transactions.discard()
        raise
