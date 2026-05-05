from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from schemas.transaction import (
    Type, ExpenseCreate, ExpenseRead, ExpenseUpdate, IncomeCreate, IncomeRead,
    IncomeUpdate, TransferCreate, TransferRead, TransferUpdate
)


router = APIRouter(
    prefix="/transactions",
    tags=["transactions"]
)

TRANSACTIONS = []


@router.post("/", status_code=201)
def create_transaction(transaction: ExpenseCreate | IncomeCreate | TransferCreate):
    tid = uuid4()
    TRANSACTIONS.append({"tid": tid, **transaction.dict()})
    return {
        "message": "transaction created successfully",
        "transaction": {"tid": tid, **transaction.dict()}
    }


@router.get("/{tid}", response_model=ExpenseRead | IncomeRead | TransferRead, status_code=200)
def get_transaction(tid: UUID):
    transaction = next((txn for txn in TRANSACTIONS if txn["tid"] == tid), None)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.get("/", response_model=list[ExpenseRead | IncomeRead | TransferRead], status_code=200)
def get_transactions(type: Type | None = None):
    if type == Type.EXPENSE:
        return [txn for txn in TRANSACTIONS if txn.get("from_account") is not None and txn.get("to_account") is None]
    elif type == Type.INCOME:
        return [txn for txn in TRANSACTIONS if txn.get("from_account") is None and txn.get("to_account") is not None]
    elif type == Type.TRANSFER:
        return [txn for txn in TRANSACTIONS if txn.get("from_account") is not None and txn.get("to_account") is not None]
    else:
        return TRANSACTIONS


@router.patch("/{tid}", response_model=ExpenseRead | IncomeRead | TransferRead, status_code=200)
def update_transaction(tid: UUID, update: ExpenseUpdate | IncomeUpdate | TransferUpdate):
    current = next((txn for txn in TRANSACTIONS if txn["tid"] == tid), None)
    if not current:
        raise HTTPException(status_code=404, detail="transaction not found")
    TRANSACTIONS.remove(current)
    updated = {"tid": tid, **update.dict()}
    TRANSACTIONS.append(updated)
    return updated


@router.delete("/{tid}", status_code=204)
def delete_transaction(tid: UUID):
    transaction = next((txn for txn in TRANSACTIONS if txn["tid"] == tid), None)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    TRANSACTIONS.remove(transaction)
    return {"message": "transaction deleted successfully"}
