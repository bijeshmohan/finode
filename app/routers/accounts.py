from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..dependencies import DBSession
from ..schemas.account import AccountCreate, AccountRead, AccountUpdate
from ..repositories.account import create, read, read_all, update, delete


router = APIRouter(
    prefix="/accounts",
    tags=["accounts"]
)


@router.post("/", response_model=AccountRead, status_code=201)
def create_account(account: AccountCreate, db: DBSession):
    return create(db, account)


@router.get("/{aid}", response_model=AccountRead, status_code=200)
def get_account(aid: UUID, db: DBSession):
    account = read(db, aid)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.get("/", response_model=list[AccountRead], status_code=200)
def get_accounts(db: DBSession):
    return read_all(db)


@router.patch("/{aid}", response_model=AccountRead, status_code=200)
def update_account(aid: UUID, data: AccountUpdate, db: DBSession):
    account = update(db, aid, data)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.delete("/{aid}", status_code=204)
def delete_account(aid: UUID, db: DBSession):
    account = delete(db, aid)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return {"message": "account deleted successfully"}
