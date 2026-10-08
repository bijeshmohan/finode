from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Reports
from ..schemas.report import BreakdownRead, SummaryRead, TrialBalanceRead


router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/summary", response_model=SummaryRead, status_code=200)
def get_summary(
    reports: Reports,
    date_from: date | None = None,
    date_to: date | None = None,
):
    try:
        return reports.summary(date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/breakdown", response_model=BreakdownRead, status_code=200)
def get_breakdown(
    reports: Reports,
    root: Literal["Income", "Expenses"] = "Expenses",
    date_from: date | None = None,
    date_to: date | None = None,
    depth: int = 1,
):
    try:
        return reports.breakdown(root, date_from, date_to, depth)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/trial-balance", response_model=TrialBalanceRead, status_code=200)
def get_trial_balance(reports: Reports, as_of: date | None = None):
    """Every account's debits and credits, plus a check that the books are sound."""
    return reports.trial_balance(as_of)
