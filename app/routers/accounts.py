from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Accounts
from ..schemas.account import AccountCreate, AccountRead, AccountUpdate
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
def get_account(aid: UUID, accounts: Accounts, as_of: date | None = None):
    """The account with its balance as of a day (today by default: later entries do not count yet)."""
    account = accounts.read(aid, as_of)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.get("/", response_model=list[AccountRead], status_code=200)
def get_accounts(
    accounts: Accounts,
    type: Literal["Assets", "Liabilities", "Equity", "Income", "Expenses"] | None = None,
    as_of: date | None = None,
):
    """Accounts with their balances as of a day (today by default: later entries do not count yet)."""
    return accounts.list(type, as_of)


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


def _closing(action, aid: UUID):
    try:
        return action(aid)
    except AccountInUseError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail="account not found")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{aid}/close", response_model=AccountRead, status_code=200)
def close_account(aid: UUID, accounts: Accounts):
    """Close an account (and everything inside it): its history stays, nothing more can be posted to it.
    Refused while it holds a balance or a recurring transaction still uses it."""
    return _closing(accounts.close, aid)
