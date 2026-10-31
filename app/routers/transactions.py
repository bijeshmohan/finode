from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..auth import require_authenticated_user
from ..clock import local_start_utc
from ..dependencies import Transactions
from ..limits import LimitReached
from ..schemas.transaction import (
    BatchResult,
    ChangeRead,
    HistoryRead,
    PayeeDefaultRead,
    PayeeRead,
    TransactionBatch,
    TransactionCreate,
    TransactionPreview,
    TransactionRead,
    TransactionUpdate,
)
from ..services.transaction import InvalidPostingError

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.post("/", response_model=TransactionRead | TransactionPreview, status_code=201)
def create_transaction(
    transaction: TransactionCreate,
    transactions: Transactions,
    response: Response,
    dry_run: bool = False,
):
    """Record a transaction: postings whose debits equal their credits (at least two), a date (today by default), payee, note and optional `related_id`.
    `source`, `external_id` and `source_url` say where it came from (a bank, a mail); a source's reference is used once,
    so sending the same one again with the same date and rows answers 200 with the entry already recorded, and
    nothing is created. The same reference with a different date or rows is a 400.
    With `dry_run=true` every check runs but nothing is saved: the answer (200) is the entry as it would be saved."""
    try:
        if dry_run:
            response.status_code = 200
            return transactions.preview_create(transaction)
        created, made = transactions.create_once(transaction)
        if not made:
            response.status_code = 200
        return created
    except (InvalidPostingError, LimitReached) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.post("/batch", response_model=BatchResult, status_code=201)
def create_transactions(batch: TransactionBatch, transactions: Transactions, response: Response, dry_run: bool = False):
    """Record up to 50 transactions as one: all are saved or none. An entry whose `source` and `external_id` are already
    recorded with the same date and rows is skipped (status `already_recorded`), so a batch can be sent again safely.
    Any problem refuses the whole batch (400) naming the entries at fault. With `dry_run=true` nothing is saved and the
    answer (200) shows what would be."""
    try:
        result = transactions.record_batch(batch.transactions, dry_run)
    except (InvalidPostingError, LimitReached) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    if not result.created:
        response.status_code = 200
    return result


@router.get("/payees", response_model=list[PayeeRead])
def payees(transactions: Transactions):
    """Who you have paid or been paid by, most used first (the opening-balance entries are left out)."""
    return [PayeeRead(payee=name, count=count) for name, count in transactions.payees()]


@router.get("/payee-defaults", response_model=list[PayeeDefaultRead])
def payee_defaults(transactions: Transactions, payee: str = "", limit: int = Query(default=5, ge=1, le=20)):
    """How payees are usually booked, most used first: the accounts of the newest entry with one account on each side
    (so a repeat can be filled in), and the other routes seen. `payee` narrows to those that match what is typed."""
    return transactions.payee_defaults(payee, limit)


@router.get("/deleted", response_model=list[HistoryRead])
def deleted_transactions(transactions: Transactions):
    """Entries that were deleted and are not back, newest deletion first; `id` is what to restore."""
    return transactions.restorable()


@router.get("/changes", response_model=list[ChangeRead])
def recent_changes(
    transactions: Transactions,
    since: date | None = None,
    by: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """The latest steps across all entries (made, edited, deleted), newest first, each with what it changed.
    `since` is a day; `by` is `assistant` (any), `web`, `api`, `import`, `recurring` or `mcp:<connection name>`."""
    return transactions.recent_changes(local_start_utc(since) if since else None, (by or "").strip() or None, limit)


@router.post("/deleted/{history_id}/restore", response_model=TransactionRead)
def restore_transaction(history_id: UUID, transactions: Transactions):
    """Bring a deleted entry back as it was, with its old id (checked again like any new entry)."""
    try:
        return transactions.restore(history_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="deleted transaction not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/{transaction_id}", response_model=TransactionRead, status_code=200)
def get_transaction(transaction_id: UUID, transactions: Transactions):
    """One transaction with its postings."""
    transaction = transactions.read(transaction_id)
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.get("/", response_model=list[TransactionRead], status_code=200)
def get_transactions(
    transactions: Transactions,
    account_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    text: str | None = None,
    kind: Literal["expense", "income", "transfer"] | None = None,
    category_id: UUID | None = None,
    payee: str | None = None,
    source: str | None = None,
    external_id: str | None = None,
    tag: str | None = None,
):
    """Newest first. `text` matches the payee, the note or the name of an account used; `kind` is told by the accounts
    used (spending, income or a transfer); `category_id` is a category the entry must also touch;
    `payee` is exact, capitals aside; `source` and `external_id` find the entry a source's reference stands for; `tag` finds
    entries whose note has that #hashtag."""
    try:
        return transactions.list(
            account_id, date_from, date_to, limit, offset, text, kind, category_id, payee, source, external_id, tag
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.patch("/{transaction_id}", response_model=TransactionRead | TransactionPreview, status_code=200)
def update_transaction(
    transaction_id: UUID,
    data: TransactionUpdate,
    transactions: Transactions,
    dry_run: bool = False,
):
    """Change a transaction; only the fields sent change (`related_id: null` removes the link; `source`, `external_id` and `source_url` can be set or, with null, cleared).
    With `dry_run=true` every check runs but nothing is saved: the answer is the entry as it would read afterwards."""
    try:
        if dry_run:
            return transactions.preview_update(transaction_id, data)
        transaction = transactions.update(transaction_id, data)
    except InvalidPostingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transaction


@router.delete("/{transaction_id}", status_code=204, response_model=None)
def delete_transaction(transaction_id: UUID, transactions: Transactions, response: Response, dry_run: bool = False):
    """Delete a transaction; it waits in /transactions/deleted and can be restored.
    With `dry_run=true` nothing is deleted: the answer (200) is the entry that would go."""
    try:
        if dry_run:
            response.status_code = 200
            return transactions.preview_delete(transaction_id)
        transaction = transactions.delete(transaction_id)
    except InvalidPostingError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError:
        raise HTTPException(status_code=404, detail="transaction not found") from None
    if not transaction:
        raise HTTPException(status_code=404, detail="transaction not found")
    return {"message": "transaction deleted successfully"}


@router.get("/{transaction_id}/changes", response_model=list[ChangeRead])
def transaction_changes(transaction_id: UUID, transactions: Transactions):
    """What happened to an entry, oldest first, each step with what it changed (works for a deleted one too)."""
    steps = transactions.changes(transaction_id)
    if not steps:
        raise HTTPException(status_code=404, detail="transaction not found")
    return steps


@router.get("/{transaction_id}/history", response_model=list[HistoryRead])
def transaction_history(transaction_id: UUID, transactions: Transactions):
    """What happened to an entry, oldest first (works for a deleted one too)."""
    history = transactions.history(transaction_id)
    if not history:
        raise HTTPException(status_code=404, detail="transaction not found")
    return history


@router.get("/{transaction_id}/related", response_model=list[TransactionRead])
def related_transactions(transaction_id: UUID, transactions: Transactions):
    """The entries that are related to this one (refunds, reversals), oldest first."""
    if transactions.read(transaction_id) is None:
        raise HTTPException(status_code=404, detail="transaction not found")
    return transactions.related(transaction_id)
