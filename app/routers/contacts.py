from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from ..auth import require_authenticated_user
from ..dependencies import Contacts, ContactSummaries, Obligations, Settlements, Transfers
from ..limits import LimitReached
from ..schemas.contact import (
    ActivityPage,
    ActivityPurpose,
    ContactCreate,
    ContactDeleteResult,
    ContactRead,
    ContactSummary,
    ContactUpdate,
    ObligationRead,
    SettlementCreate,
    SettlementPreview,
    SettlementRead,
    TransferCreate,
    TransferRead,
)
from ..services.account import SystemAccountError
from ..services.contact_errors import (
    ConflictError,
    ContactNotFoundError,
    ObligationNotFoundError,
    SharedExpenseNotFoundError,
)

IdempotencyKey = Annotated[
    str | None,
    Header(
        max_length=100,
        description="Send the same key again after a timeout and the first result comes back instead of a second entry.",
    ),
]

router = APIRouter(prefix="/contacts", tags=["contacts"], dependencies=[Depends(require_authenticated_user)])


def _refused(e: ValueError) -> HTTPException:
    missing = isinstance(e, ContactNotFoundError | ObligationNotFoundError | SharedExpenseNotFoundError)
    return HTTPException(status_code=404 if missing else 409 if isinstance(e, ConflictError) else 400, detail=str(e))


@router.get("/", response_model=list[ContactRead])
def list_contacts(
    contacts: Contacts,
    include_archived: bool = False,
    q: str | None = None,
    owing: Literal["receivable", "payable"] | None = None,
    sort: Literal["name", "balance"] = "name",
):
    """Your contacts, by name or (`sort=balance`) by how much is outstanding, the biggest first. Each carries the two
    ledger accounts behind it ("Due from": they owe you, "Due to": you owe them), what each holds, and the day of the
    latest thing done with them. `q` looks in name, email, phone and notes; `owing` keeps those who owe you
    (`receivable`) or whom you owe (`payable`)."""
    return contacts.list(include_archived, q, owing, sort)


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


@router.get("/{contact_id}/obligations", response_model=list[ObligationRead])
def contact_obligations(
    contact_id: UUID,
    contacts: Contacts,
    obligations: Obligations,
    direction: Literal["receivable", "payable"] | None = None,
    open_only: bool = False,
):
    """What the contact owes you and what you owe them, one row per amount, oldest first, each with how much of it
    has been settled and how much is left. `open_only` leaves out the settled ones."""
    try:
        contacts.get(contact_id)
        return obligations.list(contact_id, direction, open_only)
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{contact_id}/transfers", response_model=TransferRead, status_code=201)
def record_transfer(
    contact_id: UUID, data: TransferCreate, transfers: Transfers, idempotency_key: IdempotencyKey = None
):
    """Money sent to a contact (`loan`, `advance`, `gift`) or received from one (`borrowing`, `advance`, `gift`). A
    loan or advance leaves a receivable, a borrowing or received advance a payable, a gift nothing owed. Send an
    `Idempotency-Key` header to make a retry safe."""
    try:
        return transfers.record(contact_id, data, idempotency_key)
    except ValueError as e:
        raise _refused(e) from None


@router.get("/{contact_id}/transfers", response_model=list[TransferRead])
def list_transfers(contact_id: UUID, transfers: Transfers):
    """A contact's transfers, newest first."""
    try:
        return transfers.list(contact_id)
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{contact_id}/settlements/preview", response_model=SettlementPreview)
def preview_settlement(contact_id: UUID, data: SettlementCreate, settlements: Settlements):
    """What a settlement would clear (which obligations, how much of each, what is left over and what is still owed),
    saving nothing."""
    try:
        return settlements.preview(contact_id, data)
    except ValueError as e:
        raise _refused(e) from None


@router.post("/{contact_id}/settlements", response_model=SettlementRead, status_code=201)
def record_settlement(
    contact_id: UUID, data: SettlementCreate, settlements: Settlements, idempotency_key: IdempotencyKey = None
):
    """Settle up: `received` is the contact paying back what they owe you, `sent` you paying back what you owe them.
    `allocation_method` `fifo` clears the oldest amounts first, `manual` takes `allocations`. Nothing is cleared beyond
    what is owed: more than that needs `excess_as` to say what the rest is. Send an `Idempotency-Key` header to make a
    retry safe."""
    try:
        return settlements.record(contact_id, data, idempotency_key)
    except ValueError as e:
        raise _refused(e) from None


@router.get("/{contact_id}/settlements", response_model=list[SettlementRead])
def list_settlements(contact_id: UUID, settlements: Settlements):
    """A contact's settlements, newest first."""
    try:
        return settlements.list(contact_id)
    except ValueError as e:
        raise _refused(e) from None


@router.get("/{contact_id}/summary", response_model=ContactSummary)
def contact_summary(contact_id: UUID, summaries: ContactSummaries):
    """What the books say about the contact (receivable, payable, net), what you lent and borrowed, the expenses you
    shared and the settlements, how many obligations are open and the latest activity."""
    try:
        return summaries.summary(contact_id)
    except ValueError as e:
        raise _refused(e) from None


@router.get("/{contact_id}/activity", response_model=ActivityPage)
def contact_activity(
    contact_id: UUID,
    summaries: ContactSummaries,
    purpose: ActivityPurpose | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Everything done with the contact (loans, borrowings, advances, gifts, shared expenses, settlements), newest
    first, with the total count for paging."""
    try:
        return summaries.activity(contact_id, purpose, limit, offset)
    except ValueError as e:
        raise _refused(e) from None
