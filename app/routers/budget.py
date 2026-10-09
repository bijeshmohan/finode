from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Budget
from ..schemas.budget import BudgetAssign, BudgetFund, BudgetMove, BudgetRead, BudgetTargetSet
from ..services.budget import BudgetError


router = APIRouter(
    prefix="/budget",
    tags=["budget"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/", response_model=BudgetRead, status_code=200)
def get_budget(budget: Budget, month: date | None = None):
    """The month's budget (the current month by default): what is left to assign and each category's figures."""
    return budget.view(month)


@router.put("/categories/{aid}", response_model=BudgetRead, status_code=200)
def assign(aid: UUID, data: BudgetAssign, budget: Budget):
    """Set how much of the month a category gets (an expense account); 0 removes it."""
    try:
        return budget.assign(data.month, aid, data.amount)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/move", response_model=BudgetRead, status_code=200)
def move(data: BudgetMove, budget: Budget):
    """Move money that is available in one category to another."""
    try:
        return budget.move(data.month, data.from_category, data.to_category, data.amount)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/categories/{aid}/target", response_model=BudgetRead, status_code=200)
def set_target(aid: UUID, data: BudgetTargetSet, budget: Budget):
    """Set a category's target: monthly (assign X every month), refill (keep X available) or by_date (X by a date)."""
    try:
        return budget.set_target(aid, data.kind, data.amount, data.target_date)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/categories/{aid}/target", response_model=BudgetRead, status_code=200)
def clear_target(aid: UUID, budget: Budget):
    try:
        return budget.clear_target(aid)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/fund", response_model=BudgetRead, status_code=200)
def fund(data: BudgetFund, budget: Budget):
    """Assign what the targets still need, until nothing is left to assign."""
    try:
        return budget.fund(data.month)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e))
