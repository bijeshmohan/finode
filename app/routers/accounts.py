from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Accounts
from ..schemas.account import AccountCreate, AccountRead, AccountUpdate, HoldingRead, RegisterEntry
from ..services.account import AccountInUseError, SystemAccountError


router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.post("/", response_model=AccountRead, status_code=201)
def create_account(account: AccountCreate, accounts: Accounts):
    try:
        return accounts.create(account)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{aid}", response_model=AccountRead, status_code=200)
def get_account(aid: UUID, accounts: Accounts):
    account = accounts.read(aid)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.get("/{aid}/holding", response_model=HoldingRead, status_code=200)
def get_account_holding(aid: UUID, accounts: Accounts):
    """What an account holding another commodity is worth and what was put into it."""
    if accounts.read(aid) is None:
        raise HTTPException(status_code=404, detail="account not found")
    holding = accounts.holding(aid)
    if holding is None:
        raise HTTPException(status_code=404, detail="account does not hold anything other than the default currency")
    return holding


@router.get("/{aid}/register", response_model=list[RegisterEntry], status_code=200)
def get_account_register(aid: UUID, accounts: Accounts):
    register = accounts.register(aid)
    if register is None:
        raise HTTPException(status_code=404, detail="account not found")
    return register


@router.get("/", response_model=list[AccountRead], status_code=200)
def get_accounts(accounts: Accounts, type: Literal["Assets", "Liabilities", "Equity", "Income", "Expenses"] | None = None):
    return accounts.list(type)


@router.patch("/{aid}", response_model=AccountRead, status_code=200)
def update_account(aid: UUID, data: AccountUpdate, accounts: Accounts):
    try:
        account = accounts.update(aid, data)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail="account not found")
        raise HTTPException(status_code=400, detail=msg)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.delete("/{aid}", status_code=204)
def delete_account(aid: UUID, accounts: Accounts):
    try:
        account = accounts.delete(aid)
    except AccountInUseError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except SystemAccountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError:
        raise HTTPException(status_code=404, detail="account not found")
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return {"message": "account deleted successfully"}
