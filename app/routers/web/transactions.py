from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Request

from ...dependencies import Accounts, Transactions
from ...models.transaction import PostingSide
from ...schemas.transaction import TransactionRead
from ...templating import templates
from .accounts import build_tree
from .utils import htmx_error, htmx_refresh


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
