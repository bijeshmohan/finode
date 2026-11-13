"""JSON API for income shared with contacts (`/api/shared-incomes`): preview, record, record again and cancel."""

from uuid import UUID

from fastapi import APIRouter, Depends

from ..auth import require_authenticated_user
from ..dependencies import SharedIncomes
from ..schemas.shared_income import IncomePreview, SharedIncomeCreate, SharedIncomeRead
from .contact_utils import IdempotencyKey, refused

router = APIRouter(prefix="/shared-incomes", tags=["contacts"], dependencies=[Depends(require_authenticated_user)])


@router.post("/preview", response_model=IncomePreview)
def preview_shared_income(data: SharedIncomeCreate, incomes: SharedIncomes):
    """What income shared with people would do (your own part, what you hold for others, who received it for you) with
    nothing saved. The same checks as saving."""
    try:
        return incomes.preview(data)
    except ValueError as e:
        raise refused(e) from None


@router.post("/", response_model=SharedIncomeRead, status_code=201)
def create_shared_income(data: SharedIncomeCreate, incomes: SharedIncomes, idempotency_key: IdempotencyKey = None):
    """Record money that came in, part of it not yours. `theirs` are the parts that belong to contacts (you owe them),
    `received_by` money a contact received for you (they owe you), `deposits` what landed in your accounts. Your own part
    is the total less `theirs`; deposits and `received_by` must add up to the total."""
    try:
        return incomes.create(data, idempotency_key)
    except ValueError as e:
        raise refused(e) from None


@router.get("/{transaction_id}", response_model=SharedIncomeRead)
def get_shared_income(transaction_id: UUID, incomes: SharedIncomes):
    try:
        return incomes.read(transaction_id)
    except ValueError as e:
        raise refused(e) from None


@router.put("/{transaction_id}", response_model=SharedIncomeRead)
def replace_shared_income(transaction_id: UUID, data: SharedIncomeCreate, incomes: SharedIncomes):
    """Record it again with new parts: the entry keeps its id. Refused (409) once anything was paid back against it. An
    ordinary income entry can be turned into shared income the same way."""
    try:
        return incomes.convert(transaction_id, data, None, [], None)
    except ValueError as e:
        raise refused(e) from None


@router.post("/{transaction_id}/cancel", status_code=204)
def cancel_shared_income(transaction_id: UUID, incomes: SharedIncomes):
    """Reverse shared income for good: its entry and what it left owed go too. Refused (409) once anything was settled
    against it."""
    try:
        incomes.cancel(transaction_id)
    except ValueError as e:
        raise refused(e) from None
