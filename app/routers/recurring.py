from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Recurring
from ..schemas.recurring import RecurringCreate, RecurringRead, RecurringUpdate

router = APIRouter(
    prefix="/recurring",
    tags=["recurring"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/", response_model=list[RecurringRead])
def list_recurring(recurring: Recurring):
    """Every recurring rule (due occurrences are recorded first)."""
    recurring.process_due()
    return recurring.list()


@router.post("/", response_model=RecurringRead, status_code=201)
def create_recurring(data: RecurringCreate, recurring: Recurring):
    """Create a rule: a simple one (from/to/amount) or a split (`postings`), on a schedule."""
    try:
        created = recurring.create(data)
        recurring.process_due()  # a start date in the past is recorded straight away
        return recurring.read(created.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/{recurring_id}", response_model=RecurringRead)
def read_recurring(recurring_id: UUID, recurring: Recurring):
    """One recurring rule."""
    rule = recurring.read(recurring_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.put("/{recurring_id}", response_model=RecurringRead)
def update_recurring(recurring_id: UUID, data: RecurringUpdate, recurring: Recurring):
    """Replace a rule's details; it continues after the last recorded or skipped day."""
    try:
        rule = recurring.update(recurring_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.post("/{recurring_id}/pause", response_model=RecurringRead)
def pause_recurring(recurring_id: UUID, recurring: Recurring):
    """Stop recording a rule until it is resumed. What it already recorded is kept."""
    rule = recurring.set_active(recurring_id, False)
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.post("/{recurring_id}/resume", response_model=RecurringRead)
def resume_recurring(recurring_id: UUID, recurring: Recurring):
    """Start a paused rule again. What fell due while it was paused is skipped, not recorded late."""
    rule = recurring.set_active(recurring_id, True)
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.post("/{recurring_id}/skip", response_model=RecurringRead)
def skip_recurring(recurring_id: UUID, recurring: Recurring):
    """Leave the next occurrence out (nothing is recorded for it); the rule carries on with the one after."""
    try:
        rule = recurring.skip_next(recurring_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.delete("/{recurring_id}", status_code=204)
def delete_recurring(recurring_id: UUID, recurring: Recurring):
    """Delete a rule; the transactions it recorded are kept."""
    if not recurring.delete(recurring_id):
        raise HTTPException(status_code=404, detail="recurring transaction not found")
