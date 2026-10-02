from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Transactions
from ..schemas.transaction import (
    TransactionCreate,
    TransactionRead,
    TransactionUpdate,
)
from ..services.transaction import InvalidPostingAccountError


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
    except InvalidPostingAccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{tid}", response_model=TransactionRead, status_code=200)
def get_transaction(tid: UUID, transactions: Transactions):
    transaction = transactions.read(tid)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.get("/", response_model=list[TransactionRead], status_code=200)
def get_transactions(transactions: Transactions):
    return transactions.list()


@router.patch("/{tid}", response_model=TransactionRead, status_code=200)
def update_transaction(
    tid: UUID,
    data: TransactionUpdate,
    transactions: Transactions,
):
    try:
        transaction = transactions.update(tid, data)
    except InvalidPostingAccountError as e:
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
