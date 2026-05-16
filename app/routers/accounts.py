from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..dependencies import Accounts
from ..schemas.account import AccountCreate, AccountRead, AccountUpdate


router = APIRouter(
    prefix="/accounts",
    tags=["accounts"]
)


@router.post("/", response_model=AccountRead, status_code=201)
def create_account(account: AccountCreate, accounts: Accounts):
    return accounts.create(account)


@router.get("/{aid}", response_model=AccountRead, status_code=200)
def get_account(aid: UUID, accounts: Accounts):
    account = accounts.read(aid)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.get("/", response_model=list[AccountRead], status_code=200)
def get_accounts(accounts: Accounts):
    return accounts.list()


@router.patch("/{aid}", response_model=AccountRead, status_code=200)
def update_account(aid: UUID, data: AccountUpdate, accounts: Accounts):
    try:
        account = accounts.update(aid, data)
    except ValueError:
        raise HTTPException(status_code=404, detail="account not found")
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.delete("/{aid}", status_code=204)
def delete_account(aid: UUID, accounts: Accounts):
    try:
        account = accounts.delete(aid)
    except ValueError:
        raise HTTPException(status_code=404, detail="account not found")
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return {"message": "account deleted successfully"}
