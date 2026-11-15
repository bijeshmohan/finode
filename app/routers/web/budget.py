"""The Budgets page: the month's categories as tiles, a group's own page, the assign sheet and moving money."""

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request

from ...dependencies import Budget
from ...schemas.budget import BudgetRead
from ...services import budget_view as view
from ...services.budget import BudgetError
from ...services.budget_view import move_lines, parse_month, shift
from ...templating import grouping_for, money, templates
from .utils import htmx_error, htmx_redirect, parse_amount

router = APIRouter(prefix="/budget")


def _money(budget: Budget, data: BudgetRead | None = None):
    style = grouping_for((data or budget.view(None)).currency)
    return lambda value: money(value, style)


def _context(budget: Budget, month: date) -> dict:
    data = budget.view(month)
    page = view.budget_page(budget, month, _money(budget, data))
    return {
        "budget": page.budget,
        "category_choices": [(c.id, " › ".join(budget.category_path(c))) for c in budget.spending_categories()],
        "show_intro": page.show_intro,
        "tree": page.tree,
        "rows": page.rows,
        "unused_ids": {r.node.line.category_id for r in page.rows if r.unused},
        "unused_count": page.unused_count,
        "overspent": page.overspent,
        "month_key": page.month.strftime("%Y-%m"),
        "month_name": page.month_name,
        "previous": shift(page.month, -1).strftime("%Y-%m"),
        "next": shift(page.month, 1).strftime("%Y-%m"),
        "is_current": page.is_current,
        "active": "budget",
        "pace": page.pace,
    }


@router.get("")
def budget_page(request: Request, budget: Budget, month: str = ""):
    return templates.TemplateResponse(request, "budget.html", _context(budget, parse_month(month)))


def _group_context(budget: Budget, month: date, category_id: UUID) -> dict:
    try:
        found = view.group_page(budget, month, category_id, _money(budget))
    except LookupError:
        raise HTTPException(status_code=404, detail="category not found") from None
    return {
        **_context(budget, month),
        "group": found.group,
        "kids": found.kids,
        "edit_url": f"/budget/group/{category_id}/sheet?month={month:%Y-%m}",
        "glance": found.glance,
        "minimum": found.minimum,
    }


@router.get("/group/{category_id}")
def group_page(request: Request, budget: Budget, category_id: UUID, month: str = ""):
    """One group: what is left in it, and the categories inside it, each opening the assign sheet."""
    return templates.TemplateResponse(
        request, "budget_group.html", _group_context(budget, parse_month(month), category_id)
    )


@router.get("/group/{category_id}/sheet")
def group_sheet(request: Request, budget: Budget, category_id: UUID, month: str = ""):
    """A group's own budget in the sheet over its page: it starts at what its subcategories add up to."""
    return templates.TemplateResponse(
        request, "partials/budget_group_sheet.html", _group_context(budget, parse_month(month), category_id)
    )


@router.post("/group/{category_id}/assign")
def assign_group(
    request: Request,
    budget: Budget,
    category_id: UUID,
    month: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        budget.assign_group(when, category_id, parse_amount(amount, default=parse_amount("0")))
    except (BudgetError, ValueError) as e:
        return htmx_error(_sentence(str(e)), "#cat-sheet-error")
    return templates.TemplateResponse(
        request, "partials/budget_group_body.html", _group_context(budget, when, category_id)
    )


@router.get("/category/{category_id}/sheet")
def category_sheet(request: Request, budget: Budget, category_id: UUID, month: str = "", group: str = ""):
    """One category in the sheet over the budget: assign, what was spent, move money."""
    when = parse_month(month)
    context = _context(budget, when)
    lines = [ln for n in context["tree"] for ln in n.lines()]
    line = next((ln for ln in lines if ln.category_id == category_id and not ln.group), None)
    if line is None:
        raise HTTPException(status_code=404, detail="category not found")
    return templates.TemplateResponse(
        request,
        "partials/budget_sheet.html",
        {**context, "line": line, "group_id": group},
    )


@router.post("/assign")
def assign(
    request: Request,
    budget: Budget,
    category: Annotated[UUID, Form()],
    month: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    sheet: Annotated[str, Form()] = "",
    group: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        budget.assign(when, category, parse_amount(amount, default=parse_amount("0")))
    except (BudgetError, ValueError) as e:
        return htmx_error(str(e), "#cat-sheet-error" if sheet else "#budget-error")
    if group:  # assigned from a group's page: that page's block comes back
        try:
            return templates.TemplateResponse(
                request, "partials/budget_group_body.html", _group_context(budget, when, UUID(group))
            )
        except ValueError:
            pass
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when))


@router.get("/move")
def move_page(request: Request, budget: Budget, month: str = "", source: UUID | None = None):
    context = _context(budget, parse_month(month))
    lines = move_lines(context["budget"])
    if source is not None and not any(line.category_id == source for line in lines):
        raise HTTPException(status_code=404, detail="category not found")
    return templates.TemplateResponse(request, "budget_move.html", {**context, "lines": lines, "source": source})


@router.post("/move")
def move(
    budget: Budget,
    from_category: Annotated[str, Form()] = "",
    to_category: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    month: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    if not from_category or not to_category:  # the sheet pickers are not browser-required fields
        return htmx_error("Choose the category to move from and the one to move to.", "#form-error")
    try:
        budget.move(when, UUID(from_category), UUID(to_category), parse_amount(amount))
    except (BudgetError, ValueError) as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/budget?month={when:%Y-%m}", flash="budget-moved")


@router.post("/copy")
def copy_previous(request: Request, budget: Budget, month: Annotated[str, Form()] = ""):
    when = parse_month(month)
    try:
        budget.copy_previous(when)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when))


def _sentence(message: str) -> str:
    """The message with its first letter raised and the rest as written (a currency code or a name keeps its capitals)."""
    return message[:1].upper() + message[1:]
