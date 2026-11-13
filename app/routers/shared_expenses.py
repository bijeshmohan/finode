"""JSON API for expenses split with contacts (`/api/shared-expenses`): preview, draft, change, confirm, cancel."""

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends

from ..auth import require_authenticated_user
from ..dependencies import SharedExpenses
from ..schemas.shared_expense import ExpensePreview, SharedExpenseCreate, SharedExpenseRead, SharedExpenseUpdate
from .contact_utils import IdempotencyKey, refused

router = APIRouter(prefix="/shared-expenses", tags=["contacts"], dependencies=[Depends(require_authenticated_user)])


@router.post("/preview", response_model=ExpensePreview)
def preview_shared_expense(data: SharedExpenseCreate, expenses: SharedExpenses):
    """What an expense would do (each person's share, who owes whom, the ledger lines, and how much of the bill is
    still unpaid for) with nothing saved. The same checks as saving, except that a bill not yet fully paid for is fine."""
    try:
        return expenses.preview(data)
    except ValueError as e:
        raise refused(e) from None


@router.post("/", response_model=SharedExpenseRead, status_code=201)
def create_shared_expense(
    data: SharedExpenseCreate, expenses: SharedExpenses, confirm: bool = False, idempotency_key: IdempotencyKey = None
):
    """Save an expense split with contacts as a draft, or with `confirm=true` record it at once. The shares are worked
    out by `split_method` (`equal`, `exact` amounts, `percentage`, `shares` weights); `payments` are what you paid from
    your accounts and `contributions` what contacts paid. Only a bill fully paid for can be confirmed."""
    try:
        return expenses.create(data, confirm, idempotency_key)
    except ValueError as e:
        raise refused(e) from None


@router.get("/", response_model=list[SharedExpenseRead])
def list_shared_expenses(expenses: SharedExpenses, status: Literal["draft", "confirmed"] | None = None):
    """Your shared expenses, newest first."""
    return expenses.list(status)


@router.get("/{expense_id}", response_model=SharedExpenseRead)
def get_shared_expense(expense_id: UUID, expenses: SharedExpenses):
    try:
        return expenses.read(expense_id)
    except ValueError as e:
        raise refused(e) from None


@router.patch("/{expense_id}", response_model=SharedExpenseRead)
def update_shared_expense(expense_id: UUID, data: SharedExpenseUpdate, expenses: SharedExpenses):
    """Change a draft (only what is sent changes; a list is replaced whole). A confirmed expense is cancelled and
    entered again instead (409)."""
    try:
        return expenses.update(expense_id, data)
    except ValueError as e:
        raise refused(e) from None


@router.post("/{expense_id}/confirm", response_model=SharedExpenseRead)
def confirm_shared_expense(expense_id: UUID, expenses: SharedExpenses, idempotency_key: IdempotencyKey = None):
    """Record the expense: one ledger entry (your share spent, your payments out) and what each contact owes or is owed.
    Confirming twice is a 409; send an `Idempotency-Key` so a retry returns the first result."""
    try:
        return expenses.confirm(expense_id, idempotency_key)
    except ValueError as e:
        raise refused(e) from None


@router.post("/{expense_id}/cancel", status_code=204)
def cancel_shared_expense(expense_id: UUID, expenses: SharedExpenses):
    """Remove a draft, or reverse a confirmed expense for good: its entry and what it left owed go too. Refused (409)
    once anything was settled against it."""
    try:
        expenses.cancel(expense_id)
    except ValueError as e:
        raise refused(e) from None
