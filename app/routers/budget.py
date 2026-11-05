from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Budget, ComingUp
from ..schemas.budget import (
    BudgetAssign,
    BudgetCopy,
    BudgetMove,
    BudgetRead,
    GroupAssign,
)
from ..schemas.coming_up import ComingUpRead
from ..services.budget import BudgetError

router = APIRouter(
    prefix="/budget",
    tags=["budget"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/", response_model=BudgetRead, status_code=200)
def get_budget(budget: Budget, month: date | None = None):
    """The month's budget (the current month by default): what is left to assign and each category's figures."""
    try:
        return budget.view(month)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.get("/coming-up", response_model=ComingUpRead, status_code=200)
def coming_up(service: ComingUp, through: date | None = None):
    """What is coming up after today, to the end of this month (or to `through`, at most a year ahead): entries dated
    ahead and what recurring rules will record, those that touch an account of the budget, soonest first."""
    try:
        return service.view(through)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.put("/categories/{category_id}", response_model=BudgetRead, status_code=200)
def assign(category_id: UUID, data: BudgetAssign, budget: Budget):
    """Set how much of the month a category gets (an expense account); 0 removes it."""
    try:
        return budget.assign(data.month, category_id, data.amount)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


def _run(action, *args):
    """Run a budget action; its refusals are 400s (a missing category is a 404)."""
    try:
        return action(*args)
    except BudgetError as e:
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e)) from None


@router.post("/move", response_model=BudgetRead)
def move_money(data: BudgetMove, budget: Budget):
    """Move assigned money from one category to another (at most what is available); Ready to assign does not change."""
    return _run(budget.move, data.month, data.from_category, data.to_category, data.amount)


@router.post("/copy", response_model=BudgetRead)
def copy_previous_month(data: BudgetCopy, budget: Budget):
    """Assign a month what each category got the month before, where nothing is assigned yet (nothing is overwritten)."""
    return _run(budget.copy_previous, data.month)


@router.put("/groups/{category_id}", response_model=BudgetRead)
def assign_group(category_id: UUID, data: GroupAssign, budget: Budget):
    """Set a group's budget for a month: at least what its subcategories add up to; the rest is the group's own money."""
    return _run(budget.assign_group, data.month, category_id, data.total)


@router.post("/accounts/{account_id}/include", response_model=BudgetRead)
def include_account(account_id: UUID, budget: Budget, month: date | None = None):
    """Make an account part of the budget (its money and its spending count from now on)."""
    _run(budget.include_account, account_id)
    return _run(budget.view, month)
