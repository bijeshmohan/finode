from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Accounts
from ..models.account import AccountType
from ..schemas.account import AccountCreate, AccountRead, AccountUpdate
from ..services.account import AccountInUseError


router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    dependencies=[Depends(require_authenticated_user)],
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
def get_accounts(accounts: Accounts, type: AccountType | None = None):
    return accounts.list(type)


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
    except AccountInUseError:
        raise HTTPException(status_code=409, detail="account has postings")
    except ValueError:
        raise HTTPException(status_code=404, detail="account not found")
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return {"message": "account deleted successfully"}
