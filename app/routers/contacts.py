from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Contacts
from ..limits import LimitReached
from ..schemas.contact import ContactCreate, ContactDeleteResult, ContactRead, ContactUpdate
from ..services.account import SystemAccountError
from ..services.contact import ContactNotFoundError

router = APIRouter(prefix="/contacts", tags=["contacts"], dependencies=[Depends(require_authenticated_user)])


def _refused(e: ValueError) -> HTTPException:
    return HTTPException(status_code=404 if isinstance(e, ContactNotFoundError) else 400, detail=str(e))


@router.get("/", response_model=list[ContactRead])
def list_contacts(contacts: Contacts, include_archived: bool = False):
    """Your contacts by name. Each carries the two ledger accounts behind it: "Due from" (they owe you) and "Due to"
    (you owe them)."""
    return contacts.list(include_archived)


@router.post("/", response_model=ContactRead, status_code=201)
def create_contact(data: ContactCreate, contacts: Contacts):
    """Add a contact; its two accounts are made with it. Names are unique, capitals aside, and at most 30 characters."""
    try:
        return contacts.create(data)
    except (ValueError, LimitReached) as e:
        raise _refused(e) from None


@router.get("/{contact_id}", response_model=ContactRead)
def get_contact(contact_id: UUID, contacts: Contacts):
    contact = contacts.read(contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail="contact not found!")
    return contact


@router.patch("/{contact_id}", response_model=ContactRead)
def update_contact(contact_id: UUID, data: ContactUpdate, contacts: Contacts):
    """Change a contact's name (its two accounts are renamed with it) or details; null clears email, phone or notes."""
    try:
        return contacts.update(contact_id, data)
    except SystemAccountError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise _refused(e) from None


@router.delete("/{contact_id}", response_model=ContactDeleteResult)
def delete_contact(contact_id: UUID, contacts: Contacts):
    """Remove a contact no money ever moved with. One with entries is archived instead (refused while anything is
    owed), and the answer says which happened."""
    try:
        return contacts.delete(contact_id)
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{contact_id}/archive", response_model=ContactRead)
def archive_contact(contact_id: UUID, contacts: Contacts):
    """Hide a contact from new entries; its history stays. Refused while anything is owed either way."""
    try:
        return contacts.archive(contact_id)
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{contact_id}/restore", response_model=ContactRead)
def restore_contact(contact_id: UUID, contacts: Contacts):
    try:
        return contacts.restore(contact_id)
    except ValueError as e:
        raise _refused(e) from None
