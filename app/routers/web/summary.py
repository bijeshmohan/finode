import calendar
from decimal import Decimal

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ...clock import local_today
from ...dependencies import Reports
from ...templating import templates
from .budget import parse_month, shift


router = APIRouter(prefix="/summary")


@router.get("")
def summary_page(request: Request, reports: Reports, month: str = ""):
    this_month = local_today().replace(day=1)
    when = parse_month(month)
    if when > this_month:  # nothing to show for a month that has not started
        return RedirectResponse(f"/summary?month={this_month:%Y-%m}", status_code=303)
    report = reports.month_report(when)
    biggest = max((max(t.income, t.expenses) for t in report.trend), default=Decimal(0))
    return templates.TemplateResponse(
        request,
        "summary.html",
        {
            "report": report,
            "month_name": f"{calendar.month_name[when.month]} {when.year}",
            "is_current": when == this_month,
            "previous": shift(when, -1).strftime("%Y-%m"),
            "next": shift(when, 1).strftime("%Y-%m"),
            "scale": biggest,
            "active": "dashboard",
        },
    )
