from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_authenticated_user
from ..dependencies import Transactions
from ..limits import LimitReached
from ..schemas.transaction import (
    HistoryRead,
    PayeeRead,
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)
from ..services.transaction import InvalidPostingError

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.post("/", response_model=TransactionRead, status_code=201)
def create_transaction(
    transaction: TransactionCreate,
    transactions: Transactions,
):
    """Record a transaction: postings whose debits equal their credits (at least two), a date (today by default), payee, note and optional `related_id`."""
    try:
        return transactions.create(transaction)
    except (InvalidPostingError, LimitReached) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.get("/payees", response_model=list[PayeeRead])
def payees(transactions: Transactions):
    """Who you have paid or been paid by, most used first (the opening-balance entries are left out)."""
    return [PayeeRead(payee=name, count=count) for name, count in transactions.payees()]


@router.get("/deleted", response_model=list[HistoryRead])
def deleted_transactions(transactions: Transactions):
    """Entries that were deleted and are not back, newest deletion first; `hid` is what to restore."""
    return transactions.restorable()


@router.post("/deleted/{hid}/restore", response_model=TransactionRead)
def restore_transaction(hid: UUID, transactions: Transactions):
    """Bring a deleted entry back as it was, with its old id (checked again like any new entry)."""
    try:
        return transactions.restore(hid)
    except LookupError:
        raise HTTPException(status_code=404, detail="deleted transaction not found") from None
    except (ValueError, LimitReached) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/{tid}", response_model=TransactionRead, status_code=200)
def get_transaction(tid: UUID, transactions: Transactions):
    """One transaction with its postings."""
    transaction = transactions.read(tid)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.get("/", response_model=list[TransactionRead], status_code=200)
def get_transactions(
    transactions: Transactions,
    account: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    text: str | None = None,
    kind: Literal["expense", "income", "transfer"] | None = None,
    category: UUID | None = None,
    payee: str | None = None,
):
    """Newest first. `text` matches the payee, the note or the name of an account used; `kind` is told by the accounts
    used (spending, income or a transfer); `category` is an Expenses or Income account the entry must also touch;
    `payee` is exact, capitals aside."""
    try:
        return transactions.list(account, date_from, date_to, limit, offset, text, kind, category, payee)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.patch("/{tid}", response_model=TransactionRead, status_code=200)
def update_transaction(
    tid: UUID,
    data: TransactionUpdate,
    transactions: Transactions,
):
    """Change a transaction; only the fields sent change (`related_id: null` removes the link)."""
    try:
        transaction = transactions.update(tid, data)
    except InvalidPostingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.delete("/{tid}", status_code=204)
def delete_transaction(tid: UUID, transactions: Transactions):
    """Delete a transaction; it waits in /transactions/deleted and can be restored."""
    try:
        transaction = transactions.delete(tid)
    except InvalidPostingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError:
        raise HTTPException(status_code=404, detail="transaction not found") from None
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"message": "transaction deleted successfully"}


@router.get("/{tid}/history", response_model=list[HistoryRead])
def transaction_history(tid: UUID, transactions: Transactions):
    """What happened to an entry, oldest first (works for a deleted one too)."""
    history = transactions.history(tid)
    if not history:
        raise HTTPException(status_code=404, detail="transaction not found")
    return history


@router.get("/{tid}/related", response_model=list[TransactionRead])
def related_transactions(tid: UUID, transactions: Transactions):
    """The entries that are related to this one (refunds, reversals), oldest first."""
    if transactions.read(tid) is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transactions.related(tid)
