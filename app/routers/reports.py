from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_authenticated_user
from ..dependencies import Reports
from ..schemas.report import SummaryRead


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
