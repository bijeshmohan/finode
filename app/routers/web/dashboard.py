from fastapi import APIRouter, Request

from ...dependencies import Accounts, Reports, Transactions
from ...templating import templates
from .transactions import _to_row


router = APIRouter()

RECENT_LIMIT = 8


@router.get("/")
def dashboard(
    request: Request,
    accounts: Accounts,
    reports: Reports,
    transactions: Transactions,
):
    summary = reports.summary()
    names = {a.aid: a.name for a in accounts.list()}
    recent = [_to_row(t, names) for t in transactions.list(limit=RECENT_LIMIT)]
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"active": "dashboard", "summary": summary, "recent": recent},
    )
