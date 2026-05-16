from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..dependencies import AR
from ..schemas.account import AccountCreate, AccountRead, AccountUpdate


router = APIRouter(
    prefix="/accounts",
    tags=["accounts"]
)


@router.post("/", response_model=AccountRead, status_code=201)
def create_account(account: AccountCreate, ar: AR):
    return ar.create(account)


@router.get("/{aid}", response_model=AccountRead, status_code=200)
def get_account(aid: UUID, ar: AR):
    account = ar.read(aid)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.get("/", response_model=list[AccountRead], status_code=200)
def get_accounts(ar: AR):
    return ar.list()


@router.patch("/{aid}", response_model=AccountRead, status_code=200)
def update_account(aid: UUID, data: AccountUpdate, ar: AR):
    account = ar.update(aid, data)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.delete("/{aid}", status_code=204)
def delete_account(aid: UUID, ar: AR):
    account = ar.delete(aid)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return {"message": "account deleted successfully"}
