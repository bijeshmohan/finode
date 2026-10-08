import calendar
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request

from ...dependencies import Budget
from ...services.budget import BudgetError, month_start
from ...templating import templates
from .utils import htmx_error, htmx_redirect, parse_amount


router = APIRouter(prefix="/budget")


def parse_month(value: str) -> date:
    """'2026-10' (or any date) -> the first day of that month; the current month when empty or unreadable."""
    value = (value or "").strip()
    try:
        if len(value) == 7:
            return date.fromisoformat(value + "-01")
        return month_start(date.fromisoformat(value)) if value else month_start(None)
    except ValueError:
        return month_start(None)


def shift(month: date, by: int) -> date:
    index = month.year * 12 + month.month - 1 + by
    return date(index // 12, index % 12 + 1, 1)


def _context(budget: Budget, month: date) -> dict:
    data = budget.view(month)
    return {
        "budget": data,
        "month_key": data.month.strftime("%Y-%m"),
        "month_name": f"{calendar.month_name[data.month.month]} {data.month.year}",
        "previous": shift(data.month, -1).strftime("%Y-%m"),
        "next": shift(data.month, 1).strftime("%Y-%m"),
        "is_current": data.month == month_start(None),
        "active": "budget",
    }


@router.get("")
def budget_page(request: Request, budget: Budget, month: str = ""):
    return templates.TemplateResponse(request, "budget.html", _context(budget, parse_month(month)))


@router.post("/assign")
def assign(
    request: Request,
    budget: Budget,
    category: Annotated[UUID, Form()],
    month: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        budget.assign(when, category, parse_amount(amount, default=parse_amount("0")))
    except (BudgetError, ValueError) as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when))


@router.get("/move")
def move_page(request: Request, budget: Budget, month: str = "", source: UUID | None = None):
    when = parse_month(month)
    data = budget.view(when)
    lines = [line for line in data.lines if not line.group]
    if source is not None and not any(line.aid == source for line in lines):
        raise HTTPException(status_code=404, detail="category not found")
    return templates.TemplateResponse(
        request,
        "budget_move.html",
        {**_context(budget, when), "lines": lines, "source": source, "active": "budget"},
    )


@router.post("/move")
def move(
    budget: Budget,
    from_category: Annotated[UUID, Form()],
    to_category: Annotated[UUID, Form()],
    amount: Annotated[str, Form()] = "",
    month: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        budget.move(when, from_category, to_category, parse_amount(amount))
    except (BudgetError, ValueError) as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/budget?month={when:%Y-%m}", flash="budget-moved")
