from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_authenticated_user
from ..dependencies import Reports
from ..schemas.report import BreakdownRead, SummaryRead, TrialBalanceRead


router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/trial-balance", response_model=TrialBalanceRead, status_code=200)
def get_trial_balance(reports: Reports, as_of: date | None = None):
    """Every account's debits and credits, plus a check that the books are sound."""
    return reports.trial_balance(as_of)


@router.get("/summary", response_model=SummaryRead)
def get_summary(reports: Reports, date_from: date | None = None, date_to: date | None = None):
    """Net worth now, plus income and expenses for a period (the current month so far by default)."""
    try:
        return reports.summary(date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/breakdown", response_model=BreakdownRead)
def get_breakdown(
    reports: Reports,
    kind: Literal["expenses", "income"] = "expenses",
    date_from: date | None = None,
    date_to: date | None = None,
    depth: int = Query(default=1, ge=1, le=2),
):
    """Where the money went (or came from) in a period, per account `depth` levels below the top-level account."""
    try:
        return reports.breakdown("Expenses" if kind == "expenses" else "Income", date_from, date_to, depth)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
