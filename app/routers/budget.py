from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Budget
from ..schemas.budget import (
    BudgetAssign,
    BudgetCopy,
    BudgetMove,
    BudgetRead,
    GoalAssign,
    GoalCreate,
    GoalUpdate,
    GoalUse,
    GroupAssign,
)
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


def _run(action, *args):
    """Run a budget action; its refusals are 400s (a missing goal or account is a 404)."""
    try:
        return action(*args)
    except BudgetError as e:
        status = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))


@router.post("/move", response_model=BudgetRead)
def move_money(data: BudgetMove, budget: Budget):
    """Move assigned money from one category to another (at most what is available); Ready to assign does not change."""
    return _run(budget.move, data.month, data.from_category, data.to_category, data.amount)


@router.post("/copy", response_model=BudgetRead)
def copy_previous_month(data: BudgetCopy, budget: Budget):
    """Assign a month what each category got the month before, where nothing is assigned yet (nothing is overwritten)."""
    return _run(budget.copy_previous, data.month)


@router.put("/groups/{aid}", response_model=BudgetRead)
def assign_group(aid: UUID, data: GroupAssign, budget: Budget):
    """Set a group's budget for a month: at least what its subcategories add up to; the rest is the group's own money."""
    return _run(budget.assign_group, data.month, aid, data.total)


@router.post("/accounts/{aid}/include", response_model=BudgetRead)
def include_account(aid: UUID, budget: Budget, month: date | None = None):
    """Make an account part of the budget (its money and its spending count from now on)."""
    _run(budget.include_account, aid)
    return _run(budget.view, month)


@router.post("/goals", response_model=BudgetRead, status_code=201)
def create_goal(data: GoalCreate, budget: Budget):
    """A savings goal: an amount by a month. `set_aside_now` also sets aside this month's share."""
    return _run(budget.create_goal, data.name, data.amount, data.by, data.set_aside_now)


@router.put("/goals/{goal_id}", response_model=BudgetRead)
def update_goal(goal_id: UUID, data: GoalUpdate, budget: Budget):
    """Change a goal's name, amount or month. What is saved in it stays."""
    return _run(budget.update_goal, goal_id, data.name, data.amount, data.by)


@router.delete("/goals/{goal_id}", status_code=204)
def delete_goal(goal_id: UUID, budget: Budget):
    """Delete a goal for good: what was saved in it goes back to Ready to assign."""
    _run(budget.delete_goal, goal_id)


@router.put("/goals/{goal_id}/month", response_model=BudgetRead)
def assign_goal(goal_id: UUID, data: GoalAssign, budget: Budget):
    """Set what is set aside for a goal in a month (0 clears it; negative takes back what was saved before)."""
    return _run(budget.assign_goal, data.month, goal_id, data.amount)


@router.post("/goals/{goal_id}/use", response_model=BudgetRead)
def use_goal(goal_id: UUID, data: GoalUse, budget: Budget):
    """Hand money a goal saved to the category that paid for something; Ready to assign does not change."""
    return _run(budget.use_goal, data.month, goal_id, data.category, data.amount)
