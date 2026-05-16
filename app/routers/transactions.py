from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..dependencies import TR
from ..schemas.transaction import (
    Type, TransactionCreate, TransactionRead, TransactionUpdate
)


router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)


@router.post("/", response_model=TransactionRead, status_code=201)
def create_transaction(
    transaction: TransactionCreate,
    tr: TR,
):
    return tr.create(transaction)


@router.get("/{tid}", response_model=TransactionRead, status_code=200)
def get_transaction(tid: UUID, tr: TR):
    transaction = tr.read(tid)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.get("/", response_model=list[TransactionRead], status_code=200)
def get_transactions(tr: TR, type: Type | None = None):
    transactions = tr.list()
    if type == Type.EXPENSE:
        return [t for t in transactions if t.source is not None and t.destination is None]
    if type == Type.INCOME:
        return [t for t in transactions if t.source is None and t.destination is not None]
    if type == Type.TRANSFER:
        return [t for t in transactions if t.source is not None and t.destination is not None]
    return transactions


@router.patch("/{tid}", response_model=TransactionRead, status_code=200)
def update_transaction(
    tid: UUID,
    data: TransactionUpdate,
    tr: TR,
):
    transaction = tr.update(tid, data)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.delete("/{tid}", status_code=204)
def delete_transaction(tid: UUID, tr: TR):
    transaction = tr.delete(tid)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"message": "transaction deleted successfully"}
