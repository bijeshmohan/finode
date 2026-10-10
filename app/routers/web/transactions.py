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
    default = accounts.default_currency().code
    wanted = extra.get("transaction").currency if extra.get("transaction") else None
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


def split_postings(
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


def _after_save(back: str, another: str) -> str:
    if another:
        return "/transactions/new" + (f"?{urlencode({'back': back})}" if back else "")
    return safe_back(back)


def form_rows(postings, side: PostingSide, account_id: UUID | None = None) -> list[dict]:
    """The rows of one side of the form: the transaction's own postings, or one blank row (maybe with an account)."""
    found = [{"posting": p, "account": p.account} for p in postings if p.side == side]
    return found or [{"posting": None, "account": account_id}]


@router.get("/new")
def new_transaction_page(
    request: Request,
    accounts: Accounts,
    account: UUID | None = None,
    back: str = "",
    mode: str = "",  # old links; the form is one page now
):
    all_accounts = accounts.list()
    from_id = to_id = None
    roots_of = {n.account.aid: r.account.name for r in build_tree(all_accounts) for n in r.walk()}
    if account is not None:
        # From an expense category the money arrives there; from anything else it leaves.
        if roots_of.get(account) == "Expenses":
            to_id = account
        elif account in roots_of:
            from_id = account
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        form_context(
            accounts,
            today=date.today().isoformat(),
            transaction=None,
            total="",
            from_rows=form_rows([], PostingSide.CREDIT, from_id),
            to_rows=form_rows([], PostingSide.DEBIT, to_id),
            kind={"Income": "income", "Equity": "other"}.get(roots_of.get(account), "expense"),
            account=account,
            back=safe_back(back, ""),
            back_url=safe_back(back),
        ),
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
        _after_save(back, another),
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
                postings=split_postings(account, side, amount, value),
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(
        _after_save(back, another),
        flash="transaction-saved-next" if another else "transaction-saved",
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
    total = sum((p.value for p in transaction.postings if p.side == PostingSide.DEBIT), Decimal(0))
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        form_context(
            accounts,
            editing=True,
            transaction=transaction,
            total=total,
            from_rows=form_rows(transaction.postings, PostingSide.CREDIT),
            to_rows=form_rows(transaction.postings, PostingSide.DEBIT),
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
        lambda: (currency.strip() or None, split_postings(account, side, amount, value)),
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
