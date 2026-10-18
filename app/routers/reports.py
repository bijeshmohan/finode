from datetime import date

from fastapi import APIRouter, Depends

from ..auth import require_authenticated_user
from ..dependencies import Reports
from ..schemas.report import TrialBalanceRead


router = APIRouter(
    prefix="/reports",
    tags=["reports"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get("/trial-balance", response_model=TrialBalanceRead, status_code=200)
def get_trial_balance(reports: Reports, as_of: date | None = None):
    """Every account's debits and credits, plus a check that the books are sound."""
    return reports.trial_balance(as_of)
