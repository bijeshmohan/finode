import calendar
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request

from ...clock import FIRST_MONTH, LAST_MONTH, month_progress
from ...dependencies import Budget
from ...schemas.budget import BudgetLine
from ...services.budget import BudgetError, month_start
from ...templating import grouping_for, money, templates
from .utils import htmx_error, htmx_redirect, parse_amount

router = APIRouter(prefix="/budget")


def parse_month(value: str) -> date:
    """'2026-10' (or any date) -> the first day of that month; the current month when empty or unreadable."""
    value = (value or "").strip()
    try:
        if len(value) == 7:
            return month_start(date.fromisoformat(value + "-01"))
        return month_start(date.fromisoformat(value)) if value else month_start(None)
    except ValueError:
        return month_start(None)


def shift(month: date, by: int) -> date:
    """The month `by` months away; at the ends of the calendar finode works in, the month it already is."""
    index = month.year * 12 + month.month - 1 + by
    moved = date(index // 12, index % 12 + 1, 1) if 1 <= index // 12 <= 9998 else month
    return moved if FIRST_MONTH <= moved <= LAST_MONTH else month


class Node:
    """A category in the budget: a group (with its subcategories, and its own 'everything else' line) or a plain category.
    Accounts go two levels deep, so a subcategory is never a group itself."""

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
    def used(self) -> bool:
        return any(ln.assigned or ln.activity or ln.available or ln.overspent_last_month for ln in self.lines())

    @property
    def count(self) -> int:
        """The categories directly inside (not counting the group's own line)."""
        return len(self.children)


def other_line(group: BudgetLine) -> BudgetLine:
    """The part of a group that is in none of its subcategories: money can be assigned to it and spent from it."""
    zero = Decimal("0.00")
    return BudgetLine(
        category_id=group.category_id,
        name=f"{group.name} (other)",
        path=group.path,
        depth=group.depth + 1,
        assigned=zero,
        activity=zero,
        available=zero,
        overspent_last_month=zero,
    )


def build_tree(lines: list[BudgetLine]) -> list[Node]:
    """The flat display-order lines as a tree. Every group gets an 'everything else' line (made up when the
    budget has none yet, so money can be assigned at group level as well as to the subcategories)."""
    roots: list[Node] = []
    stack: list[Node] = []
    for line in lines:
        if (
            stack
            and line.category_id == stack[-1].line.category_id
            and line.name.endswith("(other)")
            and not line.group
        ):
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


def _by_assigned(nodes: list[Node]) -> list[Node]:
    """Biggest budget first, then by name."""
    return sorted(nodes, key=lambda n: (-n.line.assigned, n.line.name.lower()))


def _hint(node: Node, style: str = "western") -> str:
    """The small line under a category's name: the three biggest things inside a group and '+N'; for a plain category
    what needs a look (last month's overspending)."""
    if node.is_group:
        inside = [c.line.name for c in _by_assigned(node.children) if c.line.assigned or c.line.activity] or [
            c.line.name for c in node.children
        ]
        return " · ".join(inside[:3] + ([f"+{len(inside) - 3}"] if len(inside) > 3 else []))
    line = node.line
    parts = []
    if line.overspent_last_month:
        parts.append(f"{money(line.overspent_last_month, style)} overspent last month")
    return " · ".join(parts)


def _glance(data) -> dict:
    """The month (or a group) at a glance, worked out as Home does: what is left, and what was spent out of what there was to spend."""
    to_spend = data.activity + max(data.available, Decimal(0))
    return {
        "left": data.available,
        "spent": data.activity,
        "of": to_spend,
        "percent": int(min(max(data.activity / to_spend, Decimal(0)), Decimal(1)) * 100) if to_spend > 0 else 0,
        "planned": data.assigned > 0 or data.available > 0,
    }


def _context(budget: Budget, month: date) -> dict:
    data = budget.view(month)
    tree = build_tree(data.lines)
    # Whole groups with nothing in them (nothing assigned, spent or planned) are tucked away once anything is in use;
    # plain top-level categories always show, so there is always something to tap and assign to.
    unused = [n for n in tree if n.is_group and not n.used] if any(n.used for n in tree) else []
    return {
        "budget": data,
        "category_choices": [(c.id, " › ".join(budget.category_path(c))) for c in budget.spending_categories()],
        # A short welcome until the first amount is assigned.
        "show_intro": not budget.br.list(),
        "tree": tree,
        "rows": [{"node": n, "hint": _hint(n, grouping_for(data.currency))} for n in _by_assigned(tree)],
        "unused_ids": {n.line.category_id for n in unused},
        "unused_count": len(unused),
        # More spent than there was to spend in all the categories together (a single overspent category shows on its own bar).
        "overspent": -data.available if data.available < 0 else Decimal("0.00"),
        "month_key": data.month.strftime("%Y-%m"),
        "month_name": f"{calendar.month_name[data.month.month]} {data.month.year}",
        "previous": shift(data.month, -1).strftime("%Y-%m"),
        "next": shift(data.month, 1).strftime("%Y-%m"),
        "is_current": data.month == month_start(None),
        "active": "budget",
        # Only the current month has a "today": the tick on the bars shows how far through it we are.
        "pace": month_progress() if data.month == month_start(None) else None,
    }


@router.get("")
def budget_page(request: Request, budget: Budget, month: str = ""):
    return templates.TemplateResponse(request, "budget.html", _context(budget, parse_month(month)))


def _group_context(budget: Budget, month: date, category_id: UUID) -> dict:
    context = _context(budget, month)
    node = next((n for n in context["tree"] if n.line.category_id == category_id and n.is_group), None)
    if node is None:
        raise HTTPException(status_code=404, detail="category not found")
    return {
        **context,
        "group": node,
        "kids": [
            {"node": c, "hint": _hint(c, grouping_for(context["budget"].currency))} for c in _by_assigned(node.children)
        ],
        "edit_url": f"/budget/group/{category_id}/sheet?month={month:%Y-%m}",
        "glance": _glance(node.line),
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
    when = parse_month(month)
    context = _group_context(budget, when, category_id)
    return templates.TemplateResponse(
        request,
        "partials/budget_group_sheet.html",
        {**context, "minimum": budget.group_minimum(when, category_id, context["budget"])},
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
        return htmx_error(str(e).capitalize(), "#cat-sheet-error")
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
    when = parse_month(month)
    data = budget.view(when)
    lines = [line for line in data.lines if not line.group]
    if source is not None and not any(line.category_id == source for line in lines):
        raise HTTPException(status_code=404, detail="category not found")
    return templates.TemplateResponse(
        request,
        "budget_move.html",
        {**_context(budget, when), "lines": lines, "source": source, "active": "budget"},
    )


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
    return message[:1].upper() + message[1:]
