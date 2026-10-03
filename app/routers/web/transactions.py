from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode
from uuid import UUID

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...dependencies import Accounts, Transactions
from ...models.transaction import PostingSide
from ...schemas.transaction import (
    PostingCreate,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)
from ...templating import templates
from .accounts import build_tree, posting_groups
from .utils import htmx_error, htmx_redirect, htmx_refresh, parse_amount, validation_message


router = APIRouter(prefix="/transactions")

PAGE_SIZE = 25


@dataclass
class TransactionRow:
    transaction: TransactionRead
    debits: list[str]
    credits: list[str]
    amount: Decimal


def _to_row(transaction: TransactionRead, names: dict[UUID, str]) -> TransactionRow:
    def side_names(side: PostingSide) -> list[str]:
        found: list[str] = []
        for posting in transaction.postings:
            name = names.get(posting.account, "?")
            if posting.side == side and name not in found:
                found.append(name)
        return found

    amount = sum(
        (p.amount for p in transaction.postings if p.side == PostingSide.DEBIT),
        Decimal("0.00"),
    )
    return TransactionRow(
        transaction=transaction,
        debits=side_names(PostingSide.DEBIT),
        credits=side_names(PostingSide.CREDIT),
        amount=amount,
    )


def _parse_date(value: str) -> date | None:
    value = value.strip()
    return date.fromisoformat(value) if value else None


@router.get("")
def transactions_page(
    request: Request,
    accounts: Accounts,
    transactions: Transactions,
    account: str = "",
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
):
    all_accounts = accounts.list()
    names = {a.aid: a.name for a in all_accounts}
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
    rows = [_to_row(t, names) for t in found[:PAGE_SIZE]]
    has_next = len(found) > PAGE_SIZE

    filters = {"account": account, "date_from": date_from, "date_to": date_to}
    query = {k: v for k, v in filters.items() if v}
    return templates.TemplateResponse(
        request,
        "transactions.html",
        {
            "active": "transactions",
            "rows": rows,
            "error": error,
            "filters": filters,
            "roots": build_tree(all_accounts),
            "page": page,
            "prev_url": f"/app/transactions?{urlencode({**query, 'page': page - 1})}" if page > 1 else None,
            "next_url": f"/app/transactions?{urlencode({**query, 'page': page + 1})}" if has_next else None,
        },
    )


@router.post("/{tid}/delete")
def delete_transaction(tid: UUID, transactions: Transactions):
    try:
        transactions.delete(tid)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_refresh()


def _form_context(accounts: Accounts, **extra) -> dict:
    return {
        "active": "transactions",
        "hide_fab": True,
        "groups": posting_groups(build_tree(accounts.list())),
        **extra,
    }


def _split_postings(account: list[str], side: list[str], amount: list[str]) -> list[PostingCreate]:
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


@router.get("/new")
def new_transaction_page(request: Request, accounts: Accounts, mode: str = "simple"):
    mode = "split" if mode == "split" else "simple"
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        _form_context(accounts, mode=mode, today=date.today().isoformat(), transaction=None, postings=[]),
    )


@router.get("/rows/new")
def new_posting_row(request: Request, accounts: Accounts):
    return templates.TemplateResponse(
        request, "partials/posting_row.html", _form_context(accounts, posting=None)
    )


@router.post("")
def create_simple_transaction(
    transactions: Transactions,
    amount: Annotated[str, Form()] = "",
    from_account: Annotated[str, Form()] = "",
    to_account: Annotated[str, Form()] = "",
    date_: Annotated[str, Form(alias="date")] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
):
    try:
        if not from_account or not to_account:
            raise ValueError("choose both a from and a to account!")
        if from_account == to_account:
            raise ValueError("the from and to accounts must differ!")
        value = parse_amount(amount)
        transactions.create(
            TransactionCreate(
                date=date_ or date.today(),
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                postings=[
                    PostingCreate(account=UUID(to_account), side=PostingSide.DEBIT, amount=value),
                    PostingCreate(account=UUID(from_account), side=PostingSide.CREDIT, amount=value),
                ],
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect("/app/transactions")


@router.post("/split")
def create_split_transaction(
    transactions: Transactions,
    account: Annotated[list[str], Form()] = [],
    side: Annotated[list[str], Form()] = [],
    amount: Annotated[list[str], Form()] = [],
    date_: Annotated[str, Form(alias="date")] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
):
    try:
        transactions.create(
            TransactionCreate(
                date=date_ or date.today(),
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                postings=_split_postings(account, side, amount),
            )
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect("/app/transactions")


@router.get("/{tid}/edit")
def edit_transaction_page(request: Request, tid: UUID, accounts: Accounts, transactions: Transactions):
    transaction = transactions.read(tid)
    if transaction is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return templates.TemplateResponse(
        request,
        "transaction_form.html",
        _form_context(accounts, mode="edit", transaction=transaction, postings=transaction.postings),
    )


@router.post("/{tid}/edit")
def update_transaction(
    tid: UUID,
    transactions: Transactions,
    date_: Annotated[str, Form(alias="date")],
    account: Annotated[list[str], Form()] = [],
    side: Annotated[list[str], Form()] = [],
    amount: Annotated[list[str], Form()] = [],
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
):
    try:
        transactions.update(
            tid,
            TransactionUpdate(
                date=date_ or None,
                payee=payee.strip() or None,
                comment=comment.strip() or None,
                postings=_split_postings(account, side, amount),
            ),
        )
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        if "not found" in str(e) and f"'{tid}'" in str(e):
            raise HTTPException(status_code=404, detail="transaction not found")
        return htmx_error(str(e), "#form-error")
    return htmx_redirect("/app/transactions")
