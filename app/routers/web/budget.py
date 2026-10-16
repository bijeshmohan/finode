import calendar
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request

from ...clock import month_progress
from ...dependencies import Budget
from ...repositories.profile import ProfileRepository
from ...services.budget import BudgetError, month_start
from ...schemas.budget import TARGET_KINDS, BudgetLine
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


class Node:
    """A category in the budget: a group (with its sub-categories, and its own 'everything else' line) or a plain category.
    Accounts go two levels deep, so a sub-category is never a group itself."""

    def __init__(self, line: BudgetLine):
        self.line = line
        self.children: list[Node] = []
        self.other: BudgetLine | None = None

    @property
    def is_group(self) -> bool:
        return bool(self.children)

    def lines(self):
        """Every category line inside, the group's own 'everything else' line included."""
        if not self.is_group:
            return [self.line]
        return ([self.other] if self.other is not None else []) + [child.line for child in self.children]

    @property
    def over(self) -> int:
        return sum(1 for l in self.lines() if l.available < 0)

    @property
    def used(self) -> bool:
        return any(
            l.assigned or l.activity or l.available or l.overspent_last_month or l.underfunded or l.target or l.note
            for l in self.lines()
        )

    @property
    def count(self) -> int:
        """The categories directly inside (not counting the group's own line)."""
        return len(self.children)


def other_line(group: BudgetLine) -> BudgetLine:
    """The part of a group that is in none of its sub-categories: money can be assigned to it and spent from it."""
    zero = Decimal("0.00")
    return BudgetLine(
        aid=group.aid, name=f"{group.name} (other)", path=group.path, depth=group.depth + 1,
        assigned=zero, activity=zero, available=zero, overspent_last_month=zero, needed=zero, underfunded=zero,
    )


def build_tree(lines: list[BudgetLine]) -> list[Node]:
    """The flat display-order lines as a tree. Every group gets an 'everything else' line (made up when the
    budget has none yet, so money can be assigned at group level as well as to the sub-categories)."""
    roots: list[Node] = []
    stack: list[Node] = []
    for line in lines:
        if stack and line.aid == stack[-1].line.aid and line.name.endswith("(other)") and not line.group:
            stack[-1].other = line
            continue
        node = Node(line)
        while stack and stack[-1].line.depth >= line.depth:
            stack.pop()
        (stack[-1].children if stack else roots).append(node)
        if line.group:
            stack.append(node)

    for node in roots:
        if node.is_group and node.other is None:
            node.other = other_line(node.line)
    return roots


def _context(budget: Budget, month: date) -> dict:
    data = budget.view(month)
    advanced = ProfileRepository(budget.br.db, budget.br.uid).advanced()
    tree = build_tree(data.lines)
    # Whole groups with nothing in them (nothing assigned, spent or planned) are tucked away once anything is in use;
    # plain top-level categories always show, so there is always something to tap and assign to.
    unused = [n for n in tree if n.is_group and not n.used] if any(n.used for n in tree) else []
    return {
        "budget": data,
        "tree": tree,
        "unused_ids": {n.line.aid for n in unused},
        "unused_count": len(unused),
        "attention": sum(
            1 for flag in (
                bool(data.left_out_accounts), bool(data.overspent_last_month), advanced and bool(data.underfunded), bool(data.copyable)
            ) if flag
        ),
        "month_key": data.month.strftime("%Y-%m"),
        "month_name": f"{calendar.month_name[data.month.month]} {data.month.year}",
        "previous": shift(data.month, -1).strftime("%Y-%m"),
        "next": shift(data.month, 1).strftime("%Y-%m"),
        "is_current": data.month == month_start(None),
        "active": "budget",
        "advanced": advanced,
        # Only the current month has a "today": the tick on the bars shows how far through it we are.
        "pace": month_progress() if data.month == month_start(None) else None,
    }


@router.get("")
def budget_page(request: Request, budget: Budget, month: str = ""):
    return templates.TemplateResponse(request, "budget.html", _context(budget, parse_month(month)))


@router.get("/category/{aid}/sheet")
def category_sheet(request: Request, budget: Budget, aid: UUID, month: str = ""):
    """One category in the sheet over the budget: assign, what was spent, the target, the week by week."""
    when = parse_month(month)
    context = _context(budget, when)
    lines = [l for n in context["tree"] for l in n.lines()]
    line = next((l for l in lines if l.aid == aid and not l.group), None)
    if line is None:
        raise HTTPException(status_code=404, detail="category not found")
    return templates.TemplateResponse(request, "partials/budget_sheet.html", {**context, "line": line})


@router.post("/assign")
def assign(
    request: Request,
    budget: Budget,
    category: Annotated[UUID, Form()],
    month: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    sheet: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        budget.assign(when, category, parse_amount(amount, default=parse_amount("0")))
    except (BudgetError, ValueError) as e:
        return htmx_error(str(e), "#cat-sheet-error" if sheet else "#budget-error")
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


@router.post("/fund")
def fund(request: Request, budget: Budget, month: Annotated[str, Form()] = ""):
    when = parse_month(month)
    try:
        budget.fund(when)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when))


def _target_line(budget: Budget, month: date, category: UUID):
    line = next((l for l in budget.view(month).lines if l.aid == category and not l.name.endswith("(other)")), None)
    if line is None:
        raise HTTPException(status_code=404, detail="category not found")
    return line


@router.get("/target")
def target_page(request: Request, budget: Budget, category: UUID, month: str = ""):
    when = parse_month(month)
    return templates.TemplateResponse(
        request, "budget_target.html", {**_context(budget, when), "line": _target_line(budget, when, category)}
    )


@router.post("/target")
def set_target(
    budget: Budget,
    category: Annotated[UUID, Form()],
    kind: Annotated[str, Form()] = "monthly",
    amount: Annotated[str, Form()] = "",
    target_date: Annotated[str, Form()] = "",
    weekday: Annotated[str, Form()] = "",
    month: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        if kind not in TARGET_KINDS:
            raise BudgetError("choose what kind of target it is!")
        day = None
        if kind in ("by_date", "yearly"):
            try:
                day = date.fromisoformat(target_date.strip() + "-01") if len(target_date.strip()) == 7 else date.fromisoformat(target_date.strip())
            except ValueError:
                raise BudgetError("choose the month the money is needed by!" if kind == "by_date" else "choose the month it falls due each year!")
        day_of_week = None
        if kind == "weekly":
            try:
                day_of_week = int(weekday)
            except ValueError:
                raise BudgetError("choose the day of the week!")
        budget.set_target(category, kind, parse_amount(amount), day, day_of_week)
    except (BudgetError, ValueError) as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/budget?month={when:%Y-%m}", flash="budget-target")


@router.post("/note")
def set_note(
    budget: Budget,
    category: Annotated[UUID, Form()],
    note: Annotated[str, Form()] = "",
    month: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        budget.set_note(category, note)
    except (BudgetError, ValueError) as e:
        return htmx_error(str(e), "#note-error")
    return htmx_redirect(f"/budget?month={when:%Y-%m}", flash="budget-note")


@router.post("/target/delete")
def clear_target(budget: Budget, category: Annotated[UUID, Form()], month: Annotated[str, Form()] = ""):
    when = parse_month(month)
    try:
        budget.clear_target(category)
    except BudgetError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/budget?month={when:%Y-%m}", flash="budget-target-cleared")


@router.post("/accounts/{aid}/include")
def include_account(request: Request, budget: Budget, aid: UUID, month: Annotated[str, Form()] = ""):
    when = parse_month(month)
    try:
        budget.include_account(aid)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when))


@router.post("/copy")
def copy_previous(request: Request, budget: Budget, month: Annotated[str, Form()] = ""):
    when = parse_month(month)
    try:
        budget.copy_previous(when)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when))
