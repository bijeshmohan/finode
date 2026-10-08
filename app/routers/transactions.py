from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_authenticated_user
from ..dependencies import Transactions
from ..schemas.transaction import (
    HistoryRead,
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
    try:
        return transactions.create(transaction)
    except InvalidPostingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/deleted", response_model=list[HistoryRead], status_code=200)
def get_deleted_transactions(transactions: Transactions):
    """Transactions that were deleted, as they were when deleted, newest first."""
    return transactions.deleted()


@router.get("/{tid}/history", response_model=list[HistoryRead], status_code=200)
def get_transaction_history(tid: UUID, transactions: Transactions):
    """Creation, edits and deletion of a transaction, oldest first (also for a deleted one)."""
    history = transactions.history(tid)
    if not history:
        raise HTTPException(status_code=404, detail="transaction not found")
    return history


@router.get("/{tid}", response_model=TransactionRead, status_code=200)
def get_transaction(tid: UUID, transactions: Transactions):
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
):
    try:
        return transactions.list(account, date_from, date_to, limit, offset)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/{tid}", response_model=TransactionRead, status_code=200)
def update_transaction(
    tid: UUID,
    data: TransactionUpdate,
    transactions: Transactions,
):
    try:
        transaction = transactions.update(tid, data)
    except InvalidPostingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.delete("/{tid}", status_code=204)
def delete_transaction(tid: UUID, transactions: Transactions):
    try:
        transaction = transactions.delete(tid)
    except ValueError:
        raise HTTPException(status_code=404, detail="transaction not found")
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"message": "transaction deleted successfully"}
