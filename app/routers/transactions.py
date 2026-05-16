from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..dependencies import DBSession
from ..schemas.transaction import (
    Type, TransactionCreate, TransactionRead, TransactionUpdate
)
from ..repositories.transaction import create, read, read_all, update, delete


router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)


@router.post("/", response_model=TransactionRead, status_code=201)
def create_transaction(
    transaction: TransactionCreate,
    db: DBSession,
):
    return create(db, transaction)


@router.get("/{tid}", response_model=TransactionRead, status_code=200)
def get_transaction(tid: UUID, db: DBSession):
    transaction = read(db, tid)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.get("/", response_model=list[TransactionRead], status_code=200)
def get_transactions(db: DBSession, type: Type | None = None):
    transactions = read_all(db)
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
    db: DBSession,
):
    transaction = update(db, tid, data)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.delete("/{tid}", status_code=204)
def delete_transaction(tid: UUID, db: DBSession):
    transaction = delete(db, tid)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"message": "transaction deleted successfully"}
