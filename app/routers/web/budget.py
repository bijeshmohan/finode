import calendar
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request

from ...clock import FIRST_MONTH, LAST_MONTH, month_progress
from ...dependencies import Budget
from ...schemas.budget import BudgetLine, GoalLine
from ...services.budget import BudgetError, first_of_month, month_start, months_between
from ...templating import grouping_for, money, templates
from .utils import htmx_error, htmx_redirect, parse_amount

router = APIRouter(prefix="/budget")

# The two chips of the page.
TABS = {"spend": "Spend", "save": "Save"}


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
        aid=group.aid,
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


def _goal_rows(data) -> list[dict]:
    """The Save chip's rows: each goal with how far it is, and what this month asks of it."""
    rows = []
    for goal in data.goals:
        due = first_of_month(goal.target_date)
        reached = goal.available >= goal.amount
        rows.append(
            {
                "line": goal,
                "percent": int(min(max(goal.available / goal.amount, Decimal(0)), Decimal(1)) * 100)
                if goal.amount > 0
                else 0,
                "reached": reached,
                "months_left": max(0, months_between(data.month, due) + 1),
                "status": "reached"
                if reached
                else "overdue"
                if goal.overdue
                else "short"
                if goal.underfunded > 0
                else "done"
                if goal.needed > 0
                else "",
            }
        )
    return rows


def _context(budget: Budget, month: date, tab: str = "spend") -> dict:
    data = budget.view(month)
    tree = build_tree(data.lines)
    # Whole groups with nothing in them (nothing assigned, spent or planned) are tucked away once anything is in use;
    # plain top-level categories always show, so there is always something to tap and assign to.
    unused = [n for n in tree if n.is_group and not n.used] if any(n.used for n in tree) else []
    return {
        "budget": data,
        "tab": tab if tab in TABS else "spend",
        "tabs": TABS,
        "goal_rows": _goal_rows(data),
        # A short welcome until the first amount is assigned.
        "show_intro": not budget.br.list(),
        "tree": tree,
        "rows": [{"node": n, "hint": _hint(n, grouping_for(data.currency))} for n in _by_assigned(tree)],
        "unused_ids": {n.line.aid for n in unused},
        "unused_count": len(unused),
        # More spent than there was to spend in all the categories together (a single overspent category shows on its own bar).
        "overspent": -data.available if data.available < 0 else Decimal("0.00"),
        "attention": sum(
            1 for flag in (bool(data.left_out_accounts), bool(data.overspent_last_month), bool(data.copyable)) if flag
        ),
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
def budget_page(request: Request, budget: Budget, month: str = "", tab: str = "spend"):
    return templates.TemplateResponse(request, "budget.html", _context(budget, parse_month(month), tab))


def _group_context(budget: Budget, month: date, aid: UUID) -> dict:
    context = _context(budget, month)
    node = next((n for n in context["tree"] if n.line.aid == aid and n.is_group), None)
    if node is None:
        raise HTTPException(status_code=404, detail="category not found")
    return {
        **context,
        "group": node,
        "kids": [
            {"node": c, "hint": _hint(c, grouping_for(context["budget"].currency))} for c in _by_assigned(node.children)
        ],
        "edit_url": f"/budget/group/{aid}/sheet?month={month:%Y-%m}",
        "glance": _glance(node.line),
    }


@router.get("/group/{aid}")
def group_page(request: Request, budget: Budget, aid: UUID, month: str = ""):
    """One group: what is left in it, and the categories inside it, each opening the assign sheet."""
    return templates.TemplateResponse(request, "budget_group.html", _group_context(budget, parse_month(month), aid))


@router.get("/group/{aid}/sheet")
def group_sheet(request: Request, budget: Budget, aid: UUID, month: str = ""):
    """A group's own budget in the sheet over its page: it starts at what its subcategories add up to."""
    when = parse_month(month)
    context = _group_context(budget, when, aid)
    return templates.TemplateResponse(
        request,
        "partials/budget_group_sheet.html",
        {**context, "minimum": budget.group_minimum(when, aid, context["budget"])},
    )


@router.post("/group/{aid}/assign")
def assign_group(
    request: Request, budget: Budget, aid: UUID, month: Annotated[str, Form()] = "", amount: Annotated[str, Form()] = ""
):
    when = parse_month(month)
    try:
        budget.assign_group(when, aid, parse_amount(amount, default=parse_amount("0")))
    except (BudgetError, ValueError) as e:
        return htmx_error(str(e).capitalize(), "#cat-sheet-error")
    return templates.TemplateResponse(request, "partials/budget_group_body.html", _group_context(budget, when, aid))


@router.get("/category/{aid}/sheet")
def category_sheet(request: Request, budget: Budget, aid: UUID, month: str = "", group: str = ""):
    """One category in the sheet over the budget: assign, what was spent, move money."""
    when = parse_month(month)
    context = _context(budget, when)
    lines = [ln for n in context["tree"] for ln in n.lines()]
    line = next((ln for ln in lines if ln.aid == aid and not ln.group), None)
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
    tab: Annotated[str, Form()] = "spend",
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
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, tab))


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


@router.post("/accounts/{aid}/include")
def include_account(
    request: Request,
    budget: Budget,
    aid: UUID,
    month: Annotated[str, Form()] = "",
    tab: Annotated[str, Form()] = "spend",
):
    when = parse_month(month)
    try:
        budget.include_account(aid)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, tab))


@router.post("/copy")
def copy_previous(
    request: Request, budget: Budget, month: Annotated[str, Form()] = "", tab: Annotated[str, Form()] = "spend"
):
    when = parse_month(month)
    try:
        budget.copy_previous(when)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, tab))


def _sentence(message: str) -> str:
    return message[:1].upper() + message[1:]


def _goal_input(amount: str, by: str) -> tuple[Decimal, date]:
    """The goal form's amount and month ('2027-03'), or an explanation of what is missing."""
    if not amount.strip():
        raise ValueError("say how much you need!")
    try:
        month = date.fromisoformat(by.strip() + "-01") if len(by.strip()) == 7 else None
    except ValueError:
        month = None
    if month is None:
        raise ValueError("choose the month you need it by!")
    return parse_amount(amount), month


def _goal_form(request: Request, budget: Budget, goal=None):
    this_month = month_start(None)
    return templates.TemplateResponse(
        request,
        "budget_goal.html",
        {
            "active": "budget",
            "hide_fab": True,
            "currency": budget.accounts.currency().code,
            "earliest": shift(this_month, 1).strftime("%Y-%m"),
            "goal": goal,
        },
    )


@router.get("/goal")
def goal_page(request: Request, budget: Budget):
    """The form for a new goal: what it is for, how much, and by when."""
    return _goal_form(request, budget)


def _the_goal(budget: Budget, goal_id: UUID) -> GoalLine:
    goal = next((g for g in budget.view(None).goals if g.gid == goal_id), None)
    if goal is None:
        raise HTTPException(status_code=404, detail="goal not found")
    return goal


@router.get("/goal/{goal_id}/edit")
def goal_edit_page(request: Request, budget: Budget, goal_id: UUID):
    return _goal_form(request, budget, goal=_the_goal(budget, goal_id))


@router.get("/goal/preview")
def goal_preview(request: Request, budget: Budget, amount: str = "", by: str = ""):
    """What the goal would ask each month, as the form is filled in (nothing is saved)."""
    share = months = last = None
    error = ""
    if amount.strip() and by.strip():
        try:
            value, due = _goal_input(amount, by)
            share, months = budget.goal_share(value, due)
            last = due
        except (BudgetError, ValueError) as e:
            error = _sentence(str(e))
    return templates.TemplateResponse(
        request,
        "partials/goal_preview.html",
        {
            "share": share,
            "months": months,
            "first": month_start(None),
            "last": last,
            "error": error,
            "currency": budget.accounts.currency().code,
        },
    )


@router.get("/goal/{goal_id}/sheet")
def goal_sheet(request: Request, budget: Budget, goal_id: UUID, month: str = ""):
    """One goal in the sheet over the Save chip: how far it is, and the things to do with it."""
    when = parse_month(month)
    context = _context(budget, when, "save")
    row = next((r for r in context["goal_rows"] if r["line"].gid == goal_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="goal not found")
    return templates.TemplateResponse(request, "partials/goal_sheet.html", {**context, **row})


@router.get("/goal/{goal_id}/use")
def goal_use_sheet(request: Request, budget: Budget, goal_id: UUID, month: str = ""):
    """The second step of a goal's sheet: which category the goal's money goes to, and how much."""
    when = parse_month(month)
    context = _context(budget, when, "save")
    row = next((r for r in context["goal_rows"] if r["line"].gid == goal_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="goal not found")
    saved = row["line"].available
    lines = [ln for ln in context["budget"].lines if not ln.group]
    # The category that is most over what was planned comes first, with the amount that covers it (or all there is).
    over = min((ln for ln in lines if ln.available < 0), key=lambda ln: ln.available, default=None)
    amount = min(-over.available, saved) if over is not None else saved
    return templates.TemplateResponse(
        request,
        "partials/goal_use.html",
        {**context, **row, "categories": lines, "picked": over.aid if over else None, "amount": amount},
    )


@router.post("/goal/{goal_id}/use")
def goal_use(
    request: Request,
    budget: Budget,
    goal_id: UUID,
    category: Annotated[UUID, Form()],
    amount: Annotated[str, Form()] = "",
    month: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        budget.use_goal(when, goal_id, category, parse_amount(amount, default=parse_amount("0")))
    except (BudgetError, ValueError) as e:
        return htmx_error(_sentence(str(e)), "#cat-sheet-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, "save"))


@router.post("/goal/{goal_id}/assign")
def goal_assign(
    request: Request,
    budget: Budget,
    goal_id: UUID,
    amount: Annotated[str, Form()] = "",
    month: Annotated[str, Form()] = "",
):
    when = parse_month(month)
    try:
        budget.assign_goal(when, goal_id, parse_amount(amount, default=parse_amount("0")))
    except (BudgetError, ValueError) as e:
        return htmx_error(_sentence(str(e)), "#cat-sheet-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, "save"))


@router.post("/goal")
def create_goal(
    budget: Budget,
    name: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    by: Annotated[str, Form()] = "",
    assign_now: Annotated[str | None, Form()] = None,
):
    try:
        if not name.strip():
            raise ValueError("say what the goal is for!")
        value, due = _goal_input(amount, by)
        budget.create_goal(name.strip(), value, due, assign_now is not None)
    except (BudgetError, ValueError) as e:
        return htmx_error(_sentence(str(e)), "#form-error")
    return htmx_redirect("/budget?tab=save", flash="goal-created")


@router.post("/goal/{goal_id}")
def update_goal(
    budget: Budget,
    goal_id: UUID,
    name: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    by: Annotated[str, Form()] = "",
):
    try:
        if not name.strip():
            raise ValueError("say what the goal is for!")
        value, due = _goal_input(amount, by)
        budget.update_goal(goal_id, name.strip(), value, due)
    except (BudgetError, ValueError) as e:
        return htmx_error(_sentence(str(e)), "#form-error")
    return htmx_redirect("/budget?tab=save", flash="goal-saved")


@router.post("/goal/{goal_id}/delete")
def delete_goal(budget: Budget, goal_id: UUID):
    try:
        budget.delete_goal(goal_id)
    except (BudgetError, ValueError) as e:
        return htmx_error(_sentence(str(e)), "#cat-sheet-error")
    return htmx_redirect("/budget?tab=save", flash="goal-deleted")
