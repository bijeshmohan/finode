"""JSON API for the Add screen's save (`/api/entries`): an entry as the person chose it (rows naming accounts, categories
or people). The server decides what it records, exactly as for the web form (services/entry.py): an ordinary entry,
money to or from a person, or a gift. `/api/transactions` stays the ledger's own, line by line."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Entries
from ..limits import LimitReached
from ..schemas.entry import EntryForm, EntrySaved

router = APIRouter(prefix="/entries", tags=["entries"], dependencies=[Depends(require_authenticated_user)])


@router.post("", status_code=201, response_model=EntrySaved)
def create_entry(form: EntryForm, entries: Entries):
    """Record what the Add screen says. A category on a row posts on Expenses or Income with it; a person on a transfer is
    a loan or a borrowing (paying back what is owed first); `payee_contact` names a person as a gift."""
    try:
        return entries.create(form)
    except (ValueError, LimitReached) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.put("/{transaction_id}", response_model=EntrySaved)
def update_entry(transaction_id: UUID, form: EntryForm, entries: Entries):
    """Change an entry into what the Add screen now says, releasing what it was (a loan, a shared bill) first; all of it
    or nothing."""
    try:
        return entries.update(transaction_id, form)
    except LookupError:
        raise HTTPException(status_code=404, detail="transaction not found") from None
    except (ValueError, LimitReached) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
