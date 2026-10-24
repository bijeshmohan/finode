from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Budget
from ..schemas.budget import BudgetAssign, BudgetRead
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
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/categories/{aid}", response_model=BudgetRead, status_code=200)
def assign(aid: UUID, data: BudgetAssign, budget: Budget):
    """Set how much of the month a category gets (an expense account); 0 removes it."""
    try:
        return budget.assign(data.month, aid, data.amount)
    except BudgetError as e:
        raise HTTPException(status_code=400, detail=str(e))
