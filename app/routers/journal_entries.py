from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import JournalEntries
from ..schemas.journal import (
    JournalEntryCreate,
    JournalEntryRead,
    JournalEntryUpdate,
)


router = APIRouter(
    prefix="/journal-entries",
    tags=["journal-entries"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.post("/", response_model=JournalEntryRead, status_code=201)
def create_journal_entry(
    journal_entry: JournalEntryCreate,
    journal_entries: JournalEntries,
):
    try:
        return journal_entries.create(journal_entry)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{jid}", response_model=JournalEntryRead, status_code=200)
def get_journal_entry(jid: UUID, journal_entries: JournalEntries):
    journal_entry = journal_entries.read(jid)
    if not journal_entry:
        raise HTTPException(status_code=404, detail="journal entry not found")
    return journal_entry


@router.get("/", response_model=list[JournalEntryRead], status_code=200)
def get_journal_entries(journal_entries: JournalEntries):
    return journal_entries.list()


@router.patch("/{jid}", response_model=JournalEntryRead, status_code=200)
def update_journal_entry(
    jid: UUID,
    data: JournalEntryUpdate,
    journal_entries: JournalEntries,
):
    try:
        journal_entry = journal_entries.update(jid, data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not journal_entry:
        raise HTTPException(status_code=404, detail="journal entry not found")
    return journal_entry


@router.delete("/{jid}", status_code=204)
def delete_journal_entry(jid: UUID, journal_entries: JournalEntries):
    try:
        journal_entry = journal_entries.delete(jid)
    except ValueError:
        raise HTTPException(status_code=404, detail="journal entry not found")
    if not journal_entry:
        raise HTTPException(status_code=404, detail="journal entry not found")
    return {"message": "journal entry deleted successfully"}
