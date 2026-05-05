from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException

from schemas.account import AccountCreate, AccountRead, AccountUpdate


router = APIRouter(
    prefix="/accounts",
    tags=["accounts"]
)

ACCOUNTS = []


@router.post("/", status_code=201)
def create_account(account: AccountCreate):
    aid = uuid4()
    ACCOUNTS.append({"aid": aid, **account.dict()})
    return {
        "message": "account created successfully",
        "account": {"aid": aid, **account.dict()}
    }


@router.get("/{aid}", response_model=AccountRead, status_code=200)
def get_account(aid: UUID):
    account = next((acc for acc in ACCOUNTS if acc["aid"] == aid), None)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.get("/", response_model=list[AccountRead], status_code=200)
def get_accounts():
    return ACCOUNTS


@router.patch("/{aid}", response_model=AccountRead, status_code=200)
def update_account(aid: UUID, update: AccountUpdate):
    current = next((acc for acc in ACCOUNTS if acc["aid"] == aid), None)
    if not current:
        raise HTTPException(status_code=404, detail="account not found")
    ACCOUNTS.remove(current)
    updated = {"aid": aid, **update.dict()}
    ACCOUNTS.append(updated)
    return updated


@router.delete("/{aid}", status_code=204)
def delete_account(aid: UUID):
    account = next((acc for acc in ACCOUNTS if acc["aid"] == aid), None)
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    ACCOUNTS.remove(account)
    return {"message": "account deleted successfully"}
