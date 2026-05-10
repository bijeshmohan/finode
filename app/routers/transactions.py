from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..dependencies import DBSession
from ..schemas.transaction import (
    Type, ExpenseCreate, ExpenseRead, ExpenseUpdate, IncomeCreate, IncomeRead,
    IncomeUpdate, TransferCreate, TransferRead, TransferUpdate
)
from ..repositories.transaction import create, read, read_all, update, delete


router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)


@router.post("/", response_model=ExpenseRead | IncomeRead | TransferRead, status_code=201)
def create_transaction(
    transaction: ExpenseCreate | IncomeCreate | TransferCreate,
    db: DBSession,
):
    return create(db, transaction)


@router.get("/{tid}", response_model=ExpenseRead | IncomeRead | TransferRead, status_code=200)
def get_transaction(tid: UUID, db: DBSession):
    transaction = read(db, tid)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.get("/", response_model=list[ExpenseRead | IncomeRead | TransferRead], status_code=200)
def get_transactions(db: DBSession, type: Type | None = None):
    transactions = read_all(db)
    if type == Type.EXPENSE:
        return [t for t in transactions if t.from_account is not None and t.to_account is None]
    if type == Type.INCOME:
        return [t for t in transactions if t.from_account is None and t.to_account is not None]
    if type == Type.TRANSFER:
        return [t for t in transactions if t.from_account is not None and t.to_account is not None]
    return transactions


@router.patch("/{tid}", response_model=ExpenseRead | IncomeRead | TransferRead, status_code=200)
def update_transaction(
    tid: UUID,
    data: ExpenseUpdate | IncomeUpdate | TransferUpdate,
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
