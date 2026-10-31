from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_authenticated_user
from ..clock import local_start_utc
from ..dependencies import Accounts
from ..schemas.account import (
    AccountChangeRead,
    AccountCreate,
    AccountRead,
    AccountUpdate,
    BalanceCheck,
    ClosedAccount,
    DeletedAccount,
    MergeRequest,
    MergeResult,
    RegisterEntry,
)
from ..services.account import AccountInUseError, SystemAccountError

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.post("/", response_model=AccountRead, status_code=201)
def create_account(account: AccountCreate, accounts: Accounts):
    """Create an account under Assets, Liabilities or Equity (Expenses and Income hold categories: see /categories); `balance` sets an opening balance on an asset or liability."""
    try:
        return accounts.create(account)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/closed", response_model=list[ClosedAccount])
def closed_accounts(accounts: Accounts):
    """Accounts that were closed (and categories "deleted" while they had a history): the outermost of each closed
    branch, newest first. Reopen one with POST /accounts/{account_id}/reopen."""
    return accounts.closed()


@router.get("/deleted", response_model=list[DeletedAccount])
def deleted_accounts(accounts: Accounts):
    """Accounts and categories deleted for good that can still be restored, newest first."""
    return accounts.restorable()


@router.get("/changes", response_model=list[AccountChangeRead])
def recent_changes(
    accounts: Accounts,
    since: date | None = None,
    by: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """The latest steps across all accounts and categories (made, renamed, moved, closed, reopened, deleted), newest
    first, each with what it changed. `since` is a day; `by` is `assistant` (any), `web`, `api` or `mcp:<name>`."""
    return accounts.recent_changes(local_start_utc(since) if since else None, (by or "").strip() or None, limit)


@router.post("/deleted/{deletion_id}/restore", response_model=AccountRead)
def restore_deleted_account(deletion_id: UUID, accounts: Accounts):
    """Bring back a deleted account or category (with its old id, plan and payment links)."""
    try:
        return accounts.restore_deleted(deletion_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="deleted account not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/{account_id}", response_model=AccountRead, status_code=200)
def get_account(account_id: UUID, accounts: Accounts, as_of: date | None = None):
    """The account with its balance as of a day (today by default: later entries do not count yet)."""
    account = accounts.read(account_id, as_of)
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


@router.patch("/{account_id}", response_model=AccountRead, status_code=200)
def update_account(account_id: UUID, data: AccountUpdate, accounts: Accounts):
    """Change an account: name, note, place (`parent_id`), budget flag or payment category."""
    try:
        account = accounts.update(account_id, data)
    except ValueError as e:
        msg = str(e)
        if "not found" in msg:
            raise HTTPException(status_code=404, detail="account not found") from None
        raise HTTPException(status_code=400, detail=msg) from None
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return account


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: UUID, accounts: Accounts):
    """Delete an account for good; refused when it has entries, sub-accounts or a recurring rule (close it instead)."""
    try:
        account = accounts.delete(account_id)
    except AccountInUseError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except SystemAccountError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError:
        raise HTTPException(status_code=404, detail="account not found") from None
    if not account:
        raise HTTPException(status_code=404, detail="account not found")
    return {"message": "account deleted successfully"}


def _closing(action, account_id: UUID):
    try:
        return action(account_id)
    except AccountInUseError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    except ValueError as e:
        if "not found" in str(e):
            raise HTTPException(status_code=404, detail="account not found") from None
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/{account_id}/close", response_model=AccountRead, status_code=200)
def close_account(account_id: UUID, accounts: Accounts):
    """Close an account (and everything inside it): its history stays, nothing more can be posted to it.
    Refused while it holds a balance or a recurring transaction still uses it."""
    return _closing(accounts.close, account_id)


@router.post("/{account_id}/reopen", response_model=AccountRead, status_code=200)
def reopen_account(account_id: UUID, accounts: Accounts):
    """Reopen a closed account with everything inside it, and the groups above it."""
    return _closing(accounts.reopen, account_id)


@router.post("/{account_id}/merge", response_model=MergeResult, status_code=200)
def merge_account(account_id: UUID, data: MergeRequest, accounts: Accounts, dry_run: bool = False):
    """Make this account part of another (`into`): its entries, planned amounts, recurring rules and payment links
    become the other's and it is deleted, all or nothing. Both must be plain accounts of the same top-level account
    (this one without sub-accounts, the other open and able to take entries). Refused when an entry or rule has both on
    opposite sides, or only one is part of the budget. With `dry_run=true` nothing changes and the answer says what
    would move."""
    try:
        return accounts.merge(account_id, data.into, dry_run)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e)) from None


@router.get("/{account_id}/changes", response_model=list[AccountChangeRead])
def account_changes(account_id: UUID, accounts: Accounts):
    """What happened to an account or category, oldest first, each step with what it changed and who did it (works for a
    deleted one too)."""
    steps = accounts.changes(account_id)
    if not steps:
        raise HTTPException(status_code=404, detail="account not found")
    return steps


@router.get("/{account_id}/check-balance", response_model=BalanceCheck)
def check_balance(
    account_id: UUID,
    accounts: Accounts,
    statement_balance: Decimal,
    as_of: date | None = None,
    days: int = Query(default=14, ge=0, le=366),
):
    """Set a statement's balance against the books on the same day (today by default): the books' balance, the
    difference and the entries of the last `days` days, with those exactly as large as the difference. Nothing is
    changed. A card's or loan's balance is what is owed, as the app shows it."""
    check = accounts.check_balance(account_id, statement_balance, as_of, days)
    if check is None:
        raise HTTPException(status_code=404, detail="account not found")
    return check


@router.get("/{account_id}/register", response_model=list[RegisterEntry])
def account_register(
    account_id: UUID,
    accounts: Accounts,
    own_only: bool = False,
    limit: int | None = Query(default=None, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
):
    """The account's entries, oldest first, each with what it changed and the running balance. `own_only` leaves out
    what was posted to its sub-accounts."""
    entries = accounts.register(account_id, own_only=own_only)
    if entries is None:
        raise HTTPException(status_code=404, detail="account not found")
    return entries[offset : offset + limit] if limit else entries[offset:]
