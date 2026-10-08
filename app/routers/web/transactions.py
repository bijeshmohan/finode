from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode
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
from ...services.simple import simple_postings
from ...templating import templates
from .accounts import build_tree, posting_groups
from .utils import htmx_error, htmx_redirect, parse_amount, validation_message


router = APIRouter(prefix="/transactions")

PAGE_SIZE = 25


@dataclass
class TransactionRow:
    transaction: TransactionRead
    debits: list[str]
    credits: list[str]
    amount: Decimal  # in the transaction's own currency
    kind: str  # expense | income | transfer


@dataclass
class AccountIndex:
    names: dict[UUID, str]
    roots: dict[UUID, str]
    commodities: dict[UUID, str | None]

    @classmethod
    def build(cls, accounts: list[AccountRead]) -> "AccountIndex":
        names = {a.aid: a.name for a in accounts}
        roots = {
            node.account.aid: root.account.name
            for root in build_tree(accounts)
            for node in root.walk()
        }
        return cls(names, roots, {a.aid: a.commodity for a in accounts})


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
        (p.value for p in transaction.postings if p.side == PostingSide.DEBIT),
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
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    try:
        recurring.process_due()  # record what has fallen due; never stop the page from opening
    except Exception:
        recurring.repo.db.rollback()
    all_accounts = accounts.list()
    index = AccountIndex.build(all_accounts)
    page = max(page, 1)

    error = None
    rows: list[TransactionRow] = []
    has_next = False
    try:
        found = transactions.list(
            UUID(account) if account else None,
            _parse_date(date_from),
            _parse_date(date_to),
            PAGE_SIZE + 1,
            (page - 1) * PAGE_SIZE,
        )
    except ValueError as e:
        error = f"Invalid filter: {e}"
        found = []
    rows = [to_row(t, index) for t in found[:PAGE_SIZE]]
    has_next = len(found) > PAGE_SIZE

    filters = {"account": account, "date_from": date_from, "date_to": date_to}
    query = {k: v for k, v in filters.items() if v}
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "active": "transactions",
            "currency": accounts.default_currency().code,
            "rows": rows,
            "error": error,
            "filters": filters,
            "active_filters": len(query),
            "roots": build_tree(all_accounts),
            "page": page,
            "prev_url": f"/transactions?{urlencode({**query, 'page': page - 1})}" if page > 1 else None,
            "next_url": f"/transactions?{urlencode({**query, 'page': page + 1})}" if has_next else None,
        },
    )


@router.post("/{tid}/delete")
def delete_transaction(tid: UUID, transactions: Transactions, back: str = ""):
    try:
        transactions.delete(tid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect(safe_back(back), flash="transaction-deleted")


# Paths that are not pages of the web app.
NOT_PAGES = ("/api", "/mcp", "/static", "/.well-known", "/docs", "/openapi.json", "/app")


def safe_back(value: str | None, default: str = "/transactions") -> str:
    """Only follow return paths inside the app (never another host)."""
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value and not value.startswith(NOT_PAGES):
        return value
    return default


def _form_context(accounts: Accounts, **extra) -> dict:
    all_accounts = accounts.list()
    default = accounts.default_currency().code
    wanted = extra.get("transaction").currency if extra.get("transaction") else None
    return {
        "active": "transactions",
        "hide_fab": True,
        "groups": posting_groups(build_tree(all_accounts)),
        "currency": default,
        # The extra currency and worth fields only appear once something other than the default currency is in play.
        "multi": any(a.parent_id is not None and a.commodity != default for a in all_accounts)
        or (wanted is not None and wanted != default),
        "currencies": [c for c in accounts.commodity_choices() if c.kind == "currency" or c.code == wanted],
        "account_commodity": {a.aid: a.commodity for a in all_accounts},
        **extra,
    }


def _simple_postings(
    accounts: Accounts, amount: str, to_amount: str, from_account: str, to_account: str
) -> tuple[str, list[PostingCreate]]:
    """The simple form's fields as postings and a currency (see services.simple)."""
    if not from_account or not to_account:
        raise ValueError("choose both a from and a to account!")
    if from_account == to_account:
        raise ValueError("the from and to accounts must differ!")
    paid = parse_amount(amount)
    received = parse_amount(to_amount) if to_amount.strip() else None
    return simple_postings(accounts, paid, received, UUID(from_account), UUID(to_account))


def _split_postings(
    account: list[str], side: list[str], amount: list[str], value: list[str] | None = None
) -> list[PostingCreate]:
    value = value or [""] * len(account)
    if not (len(account) == len(side) == len(amount) == len(value)):
        raise ValueError("every posting needs an account, a side and an amount!")
    postings = []
    for account_id, posting_side, posting_amount, posting_value in zip(account, side, amount, value):
        if not account_id and not posting_amount.strip():
            continue  # untouched blank row
        if not account_id:
            raise ValueError("every posting needs an account!")
        postings.append(
            PostingCreate(
                account=UUID(account_id),
                side=PostingSide(posting_side),
                amount=parse_amount(posting_amount),
                value=parse_amount(posting_value) if posting_value.strip() else None,
            )
        )
    return postings


def _as_simple(transaction: TransactionRead, commodities: dict[UUID, str | None]) -> dict | None:
    """The simple-form fields for a plain two-sided transaction, else None."""
    postings = transaction.postings
    if len(postings) != 2 or postings[0].side == postings[1].side:
        return None
    debit = next(p for p in postings if p.side == PostingSide.DEBIT)
    credit = next(p for p in postings if p.side == PostingSide.CREDIT)
    converts = commodities.get(debit.account) != commodities.get(credit.account)
    if debit.amount != credit.amount and not converts:
        return None
    return {
        "from_id": credit.account,
        "to_id": debit.account,
        "amount": credit.amount,
        "to_amount": debit.amount if converts else "",
    }


def _after_save(back: str, another: str, mode: str) -> str:
    if another:
        params = {"back": back} if back else {}
        if mode == "split":
            params["mode"] = "split"
        return "/transactions/new" + (f"?{urlencode(params)}" if params else "")
    return safe_back(back)


@router.get("/new")
def new_transaction_page(
    request: Request,
    accounts: Accounts,
    mode: str = "simple",
    account: UUID | None = None,
    back: str = "",
):
    mode = "split" if mode == "split" else "simple"
    all_accounts = accounts.list()
    from_id = to_id = None
    if account is not None:
        roots = {n.account.aid: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
        # From an expense category the money arrives there; from anything else it leaves.
        if roots.get(account) == "Expenses":
            to_id = account
        elif account in roots:
            from_id = account
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        _form_context(
            accounts,
            mode=mode,
            today=date.today().isoformat(),
            transaction=None,
            postings=[],
            simple={"from_id": from_id, "to_id": to_id, "amount": "", "to_amount": ""},
            account=account,
            back=safe_back(back, ""),
            back_url=safe_back(back),
        ),
    )


@router.get("/rows/new")
def new_posting_row(request: Request, accounts: Accounts):
    return templates.TemplateResponse(
        request, "partials/posting_row.html", _form_context(accounts, posting=None)
    )


@router.post("")
def create_simple_transaction(
    accounts: Accounts,
    transactions: Transactions,
    amount: Annotated[str, Form()] = "",
    to_amount: Annotated[str, Form()] = "",
    from_account: Annotated[str, Form()] = "",
    to_account: Annotated[str, Form()] = "",
    date_: Annotated[str, Form(alias="date")] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
    another: Annotated[str, Form()] = "",
):
    try:
        currency, postings = _simple_postings(accounts, amount, to_amount, from_account, to_account)
        transactions.create(
            TransactionCreate(
                date=date_ or date.today(),
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                currency=currency,
                postings=postings,
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(
        _after_save(back, another, "simple"),
        flash="transaction-saved-next" if another else "transaction-saved",
    )


@router.post("/split")
def create_split_transaction(
    transactions: Transactions,
    account: Annotated[list[str], Form()] = [],
    side: Annotated[list[str], Form()] = [],
    amount: Annotated[list[str], Form()] = [],
    value: Annotated[list[str], Form()] = [],
    currency: Annotated[str, Form()] = "",
    date_: Annotated[str, Form(alias="date")] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    back: Annotated[str, Form()] = "",
    another: Annotated[str, Form()] = "",
):
    try:
        transactions.create(
            TransactionCreate(
                date=date_ or date.today(),
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                currency=currency.strip() or None,
                postings=_split_postings(account, side, amount, value),
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(
        _after_save(back, another, "split"),
        flash="transaction-saved-next" if another else "transaction-saved",
    )


@router.get("/{tid}/edit")
def edit_transaction_page(
    request: Request,
    tid: UUID,
    accounts: Accounts,
    transactions: Transactions,
    mode: str = "",
    back: str = "",
):
    transaction = transactions.read(tid)
    if transaction is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    simple = _as_simple(transaction, {a.aid: a.commodity for a in accounts.list()})
    if mode != "split" and simple is not None:
        mode = "simple"
    else:
        mode = "split"
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        _form_context(
            accounts,
            mode=mode,
            editing=True,
            can_simplify=simple is not None,
            transaction=transaction,
            postings=transaction.postings,
            simple=simple or {"from_id": None, "to_id": None, "amount": "", "to_amount": ""},
            account=None,
            back=safe_back(back, ""),
            back_url=safe_back(back),
            history=list(reversed(transactions.history(tid))),
        ),
    )


def _update(transactions: Transactions, tid: UUID, date_: str, payee: str, comment: str, postings_fn, back: str):
    try:
        currency, postings = postings_fn()
        transactions.update(
            tid,
            TransactionUpdate(
                date=date_ or None,
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                currency=currency,
                postings=postings,
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
    value: Annotated[list[str], Form()] = [],
    currency: Annotated[str, Form()] = "",
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
        lambda: (currency.strip() or None, _split_postings(account, side, amount, value)),
        back,
    )


@router.post("/{tid}/edit/simple")
def update_simple_transaction(
    tid: UUID,
    accounts: Accounts,
    transactions: Transactions,
    date_: Annotated[str, Form(alias="date")] = "",
    amount: Annotated[str, Form()] = "",
    to_amount: Annotated[str, Form()] = "",
    from_account: Annotated[str, Form()] = "",
    to_account: Annotated[str, Form()] = "",
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
        lambda: _simple_postings(accounts, amount, to_amount, from_account, to_account),
        back,
    )
