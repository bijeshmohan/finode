from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import SharedIncomes
from ..limits import LimitReached
from ..schemas.shared_income import IncomePreview, SharedIncomeCreate, SharedIncomeRead
from ..services.contact_errors import ConflictError, ContactNotFoundError, SharedIncomeNotFoundError

router = APIRouter(prefix="/shared-incomes", tags=["contacts"], dependencies=[Depends(require_authenticated_user)])

IdempotencyKey = Annotated[
    str | None,
    Header(max_length=100, description="Send the same key again after a timeout and the first result comes back."),
]


def _refused(e: ValueError) -> HTTPException:
    missing = isinstance(e, ContactNotFoundError | SharedIncomeNotFoundError)
    return HTTPException(status_code=404 if missing else 409 if isinstance(e, ConflictError) else 400, detail=str(e))


@router.post("/preview", response_model=IncomePreview)
def preview_shared_income(data: SharedIncomeCreate, incomes: SharedIncomes):
    """What income shared with people would do (your own part, what you hold for others, who received it for you) with
    nothing saved. The same checks as saving."""
    try:
        return incomes.preview(data)
    except (ValueError, LimitReached) as e:
        raise _refused(e) from None


@router.post("/", response_model=SharedIncomeRead, status_code=201)
def create_shared_income(data: SharedIncomeCreate, incomes: SharedIncomes, idempotency_key: IdempotencyKey = None):
    """Record money that came in, part of it not yours. `theirs` are the parts that belong to contacts (you owe them),
    `received_by` money a contact received for you (they owe you), `deposits` what landed in your accounts. Your own part
    is the total less `theirs`; deposits and `received_by` must add up to the total."""
    try:
        return incomes.create(data, idempotency_key)
    except (ValueError, LimitReached) as e:
        raise _refused(e) from None


@router.get("/{transaction_id}", response_model=SharedIncomeRead)
def get_shared_income(transaction_id: UUID, incomes: SharedIncomes):
    try:
        return incomes.read(transaction_id)
    except ValueError as e:
        raise _refused(e) from None


@router.put("/{transaction_id}", response_model=SharedIncomeRead)
def replace_shared_income(transaction_id: UUID, data: SharedIncomeCreate, incomes: SharedIncomes):
    """Record it again with new parts: the entry keeps its id. Refused (409) once anything was paid back against it. An
    ordinary income entry can be turned into shared income the same way."""
    try:
        return incomes.convert(transaction_id, data, None, [], None)
    except (ValueError, LimitReached) as e:
        raise _refused(e) from None


@router.post("/{transaction_id}/cancel", status_code=204)
def cancel_shared_income(transaction_id: UUID, incomes: SharedIncomes):
    """Reverse shared income for good: its entry and what it left owed go too. Refused (409) once anything was settled
    against it."""
    try:
        incomes.cancel(transaction_id)
    except ValueError as e:
        raise _refused(e) from None
