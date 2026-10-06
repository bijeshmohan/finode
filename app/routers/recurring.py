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
    recurring.process_due()
    return recurring.list()


@router.post("/", response_model=RecurringRead, status_code=201)
def create_recurring(data: RecurringCreate, recurring: Recurring):
    try:
        created = recurring.create(data)
        recurring.process_due()  # a start date in the past is recorded straight away
        return recurring.read(created.rid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{rid}", response_model=RecurringRead)
def read_recurring(rid: UUID, recurring: Recurring):
    rule = recurring.read(rid)
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.put("/{rid}", response_model=RecurringRead)
def update_recurring(rid: UUID, data: RecurringUpdate, recurring: Recurring):
    try:
        rule = recurring.update(rid, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.post("/{rid}/pause", response_model=RecurringRead)
def pause_recurring(rid: UUID, recurring: Recurring):
    rule = recurring.set_active(rid, False)
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.post("/{rid}/resume", response_model=RecurringRead)
def resume_recurring(rid: UUID, recurring: Recurring):
    try:
        rule = recurring.set_active(rid, True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return rule


@router.delete("/{rid}", status_code=204)
def delete_recurring(rid: UUID, recurring: Recurring):
    if not recurring.delete(rid):
        raise HTTPException(status_code=404, detail="recurring transaction not found")
