import calendar
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...clock import FIRST_MONTH, LAST_MONTH, month_progress
from ...config import settings
from ...dependencies import Budget
from ...repositories.profile import ProfileRepository
from ...services.budget import BudgetError, month_start
from ...schemas.profile import ProfileUpdate
from ...schemas.budget import TARGET_KINDS, BudgetLine, BudgetSaving
from ...templating import grouping_for, money, templates
from .utils import htmx_error, htmx_redirect, parse_amount


router = APIRouter(prefix="/plan")

# The page was called Budget (/budget) before it became the Plan: old links and bookmarks still arrive (GET only; the page
# itself and its forms live under /plan).
legacy = APIRouter()


@legacy.get("/budget")
@legacy.get("/budget/{rest:path}")
def budget_moved(request: Request, rest: str = ""):
    query = request.url.query
    return RedirectResponse(f"/plan{'/' + rest if rest else ''}{'?' + query if query else ''}", status_code=301)

# The sections of the page, as chips: Build and Earn only while the Plan is on (settings.plan_enabled) and the person chose them
# (profiles.plan_build / plan_earn, in the sheet behind the sliders button; their data stays when they are off).
TABS = {"earn": "Earn", "build": "Build", "spend": "Spend"}


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
        return any(
            l.assigned or l.activity or l.available or l.overspent_last_month or l.underfunded or l.target or l.note
            for l in self.lines()
        )

    @property
    def count(self) -> int:
        """The categories directly inside (not counting the group's own line)."""
        return len(self.children)


def other_line(group: BudgetLine) -> BudgetLine:
    """The part of a group that is in none of its subcategories: money can be assigned to it and spent from it."""
    zero = Decimal("0.00")
    return BudgetLine(
        aid=group.aid, name=f"{group.name} (other)", path=group.path, depth=group.depth + 1,
        assigned=zero, activity=zero, available=zero, overspent_last_month=zero, needed=zero, underfunded=zero,
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


def _hint(node: Node, advanced: bool, style: str = "western") -> str:
    """The small line under a category's name: the three biggest things inside a group and '+N'; for a plain category
    what needs a look (a target that is short, last month's overspending) and its note."""
    if node.is_group:
        inside = [c.line.name for c in _by_assigned(node.children) if c.line.assigned or c.line.activity] or [c.line.name for c in node.children]
        return " · ".join(inside[:3] + ([f"+{len(inside) - 3}"] if len(inside) > 3 else []))
    line = node.line
    parts = []
    if advanced and line.underfunded:
        parts.append(("overdue, " if line.overdue else "") + f"needs {money(line.underfunded, style)} more")
    if line.overspent_last_month:
        parts.append(f"{money(line.overspent_last_month, style)} overspent last month")
    if line.note:
        parts.append(line.note)
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


def _saving_line(saving: BudgetSaving) -> BudgetLine:
    """A Build line shown with the same rows and sheet as a category (they share the figures)."""
    return BudgetLine(
        aid=saving.aid, name=saving.name, path=saving.path, depth=1, assigned=saving.assigned, activity=saving.activity,
        available=saving.available, overspent_last_month=Decimal("0.00"), target=saving.target, needed=saving.needed, underfunded=saving.underfunded,
        overdue=saving.overdue, note=saving.note,
    )


def _saving_hint(line: BudgetLine, saving: BudgetSaving, advanced: bool, style: str) -> str:
    parts = []
    if advanced and line.underfunded:
        parts.append(("overdue, " if line.overdue else "") + f"needs {money(line.underfunded, style)} more")
    if saving.debt:
        whole = lambda value: money(value, style).replace(".00", "")  # a loan's figures are long: whole rupees fit a phone
        parts.append(f"paid {whole(line.activity)}" if line.activity else "nothing paid yet")
        parts.append(f"owed {whole(saving.balance)}")
    else:
        parts.append(f"moved {money(line.activity, style)} this month" if line.activity else "nothing moved yet")
    if line.note:
        parts.append(line.note)
    return " · ".join(parts)


def _build_rows(data, advanced: bool, style: str) -> tuple[list[dict], list[dict], dict[UUID, dict]]:
    """The Build section: the flat rows of its accounts (what the sheets look up), the list the page shows (an account
    directly under a root is a row, the accounts of a group are one row for the group, as in Spend) and the groups."""
    whole = lambda value: money(value, style).replace(".00", "")
    flat = [
        {"node": SimpleNamespace(line=_saving_line(s), is_group=False), "hint": _saving_hint(_saving_line(s), s, advanced, style), "calm": not advanced}
        for s in data.saving
    ]
    by_group: dict[UUID, list[dict]] = {}
    for s, row in zip(data.saving, flat):
        if s.group_id is not None:
            by_group.setdefault(s.group_id, []).append(row)
    groups: dict[UUID, dict] = {}
    for gid, kids in by_group.items():
        lines = [k["node"].line for k in kids]
        first = next(s for s in data.saving if s.group_id == gid)
        debt = first.debt
        owed = sum((s.balance for s in data.saving if s.group_id == gid), Decimal("0.00"))
        total = lambda attr: sum((getattr(l, attr) for l in lines), Decimal("0.00"))
        line = BudgetLine(
            aid=gid, name=first.group_name, path=":".join(first.path.split(":")[:-1]), depth=1, group=True,
            assigned=total("assigned"), activity=total("activity"), available=total("available"),
            overspent_last_month=Decimal("0.00"), needed=total("needed"), underfunded=total("underfunded"),
        )
        ranked = sorted(kids, key=lambda k: (-k["node"].line.assigned, k["node"].line.name.lower()))
        names = [k["node"].line.name for k in ranked]
        hint = " · ".join(names[:3] + ([f"+{len(names) - 3}"] if len(names) > 3 else []))
        if debt and line.activity:
            hint = f"paid {whole(line.activity)} · {hint}"
        groups[gid] = {
            "line": line, "kids": ranked, "debt": debt, "owed": owed,
            "row": {"node": SimpleNamespace(line=line, is_group=True), "hint": hint, "calm": not advanced},
        }
    shown = [row for row, s in zip(flat, data.saving) if s.group_id is None] + [g["row"] for g in groups.values()]
    shown.sort(key=lambda r: (-r["node"].line.assigned, r["node"].line.name.lower()))
    return flat, shown, groups


def _context(budget: Budget, month: date, tab: str = "spend") -> dict:
    data = budget.view(month)
    advanced = ProfileRepository(budget.br.db, budget.br.uid).advanced()
    tree = build_tree(data.lines)
    # Whole groups with nothing in them (nothing assigned, spent or planned) are tucked away once anything is in use;
    # plain top-level categories always show, so there is always something to tap and assign to.
    unused = [n for n in tree if n.is_group and not n.used] if any(n.used for n in tree) else []
    style = grouping_for(data.currency)
    tab = "build" if tab == "save" else tab  # the older address of the chip
    build_on, earn_on = ProfileRepository(budget.br.db, budget.br.uid).plan_sections()
    tabs = {
        k: v for k, v in TABS.items()
        if k == "spend" or (settings.plan_enabled and (build_on if k == "build" else earn_on))
    }
    debts = {s.aid: s for s in data.saving if s.debt}
    saving_rows, build_rows, build_groups = _build_rows(data, advanced, style)
    return {
        "budget": data,
        "tab": tab if tab in tabs else "spend",
        "tabs": tabs,
        "plan_enabled": settings.plan_enabled,
        # A short welcome until the first amount is assigned (not for people on Advanced, who know their way around).
        "show_intro": not advanced and not budget.br.list(),
        "debts": debts,
        "earning_rows": list(data.earning),
        # What the month's plan leaves over: what is expected, less what is assigned to saving and to spending.
        "unplanned": data.earning_expected - data.saving_assigned - data.assigned,
        "saving_rows": saving_rows,
        "build_rows": build_rows,
        "build_groups": build_groups,
        "tree": tree,
        "rows": [{"node": n, "hint": _hint(n, advanced, grouping_for(data.currency))} for n in _by_assigned(tree)],
        "unused_ids": {n.line.aid for n in unused},
        "unused_count": len(unused),
        # More spent than there was to spend in all the categories together (a single overspent category shows on its own bar).
        "overspent": -data.available if data.available < 0 else Decimal("0.00"),
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
        "active": "plan",
        "advanced": advanced,
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
        built = context["build_groups"].get(aid)
        if built is None:
            raise HTTPException(status_code=404, detail="category not found")
        return {
            **context, "group": SimpleNamespace(line=built["line"]), "kids": built["kids"], "edit_url": "", "glance": _glance(built["line"]),
            "build": True, "debt": built["debt"], "owed": built["owed"], "leftovers": budget.build_leftovers(aid), "tab": "build",
        }
    advanced = context["advanced"]
    return {
        **context,
        "group": node,
        "kids": [{"node": c, "hint": _hint(c, advanced, grouping_for(context["budget"].currency))} for c in _by_assigned(node.children)],
        "edit_url": f"/plan/group/{aid}/sheet?month={month:%Y-%m}",
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
    if context.get("build"):
        raise HTTPException(status_code=404, detail="a group of accounts has no budget of its own")
    return templates.TemplateResponse(
        request, "partials/budget_group_sheet.html", {**context, "minimum": budget.group_minimum(when, aid, context["budget"])}
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
    """One category in the sheet over the budget: assign, what was spent, the target, the week by week."""
    when = parse_month(month)
    context = _context(budget, when)
    lines = [l for n in context["tree"] for l in n.lines()]
    line = next((l for l in lines if l.aid == aid and not l.group), None)
    saving = earn = False
    if line is None:
        line = next((row["node"].line for row in context["saving_rows"] if row["node"].line.aid == aid), None)
        saving = line is not None
    if line is None and "earn" in context["tabs"]:
        line = next((l for l in context["earning_rows"] if l.aid == aid), None)
        earn = line is not None
    if line is None:
        raise HTTPException(status_code=404, detail="category not found")
    return templates.TemplateResponse(
        request, "partials/budget_sheet.html",
        {**context, "line": line, "group_id": group, "saving": saving, "earn": earn, "tab": "earn" if earn else "build" if saving else "spend"},
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
            return templates.TemplateResponse(request, "partials/budget_group_body.html", _group_context(budget, when, UUID(group)))
        except ValueError:
            pass
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, tab))


@router.get("/move")
def move_page(request: Request, budget: Budget, month: str = "", source: UUID | None = None):
    when = parse_month(month)
    data = budget.view(when)
    lines = [line for line in data.lines if not line.group] + [_saving_line(s) for s in data.saving]
    if source is not None and not any(line.aid == source for line in lines):
        raise HTTPException(status_code=404, detail="category not found")
    return templates.TemplateResponse(
        request,
        "budget_move.html",
        {**_context(budget, when), "lines": lines, "source": source, "active": "plan"},
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
    return htmx_redirect(f"/plan?month={when:%Y-%m}", flash="budget-moved")


@router.post("/fund")
def fund(request: Request, budget: Budget, month: Annotated[str, Form()] = "", tab: Annotated[str, Form()] = "spend"):
    when = parse_month(month)
    try:
        budget.fund(when)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, tab))


def _target_line(budget: Budget, month: date, category: UUID):
    data = budget.view(month)
    line = next((l for l in [*data.lines, *map(_saving_line, data.saving)] if l.aid == category and not l.name.endswith("(other)")), None)
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
    return htmx_redirect(f"/plan?month={when:%Y-%m}", flash="budget-target")


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
    return htmx_redirect(f"/plan?month={when:%Y-%m}", flash="budget-note")


@router.post("/target/delete")
def clear_target(budget: Budget, category: Annotated[UUID, Form()], month: Annotated[str, Form()] = ""):
    when = parse_month(month)
    try:
        budget.clear_target(category)
    except BudgetError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect(f"/plan?month={when:%Y-%m}", flash="budget-target-cleared")


@router.post("/accounts/{aid}/include")
def include_account(request: Request, budget: Budget, aid: UUID, month: Annotated[str, Form()] = "", tab: Annotated[str, Form()] = "spend"):
    when = parse_month(month)
    try:
        budget.include_account(aid)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, tab))


@router.post("/copy")
def copy_previous(request: Request, budget: Budget, month: Annotated[str, Form()] = "", tab: Annotated[str, Form()] = "spend"):
    when = parse_month(month)
    try:
        budget.copy_previous(when)
    except BudgetError as e:
        return htmx_error(str(e), "#budget-error")
    return templates.TemplateResponse(request, "partials/budget_body.html", _context(budget, when, tab))


@router.get("/configure")
def configure_sheet(request: Request, budget: Budget, month: str = "", tab: str = "spend"):
    """The sheet behind the sliders button: which sections the Plan has."""
    if not settings.plan_enabled:
        raise HTTPException(status_code=404, detail="not found")
    build_on, earn_on = ProfileRepository(budget.br.db, budget.br.uid).plan_sections()
    return templates.TemplateResponse(
        request, "partials/plan_configure.html",
        {"build_on": build_on, "earn_on": earn_on, "month_key": parse_month(month).strftime("%Y-%m"), "tab": tab},
    )


@router.post("/configure")
def configure(
    budget: Budget,
    month: Annotated[str, Form()] = "",
    tab: Annotated[str, Form()] = "spend",
    build: Annotated[str, Form()] = "",
    earn: Annotated[str, Form()] = "",
):
    if not settings.plan_enabled:
        raise HTTPException(status_code=404, detail="not found")
    build_on, earn_on = build.strip() == "1", earn.strip() == "1"
    ProfileRepository(budget.br.db, budget.br.uid).update(ProfileUpdate(plan_build=build_on, plan_earn=earn_on))
    shown = {"build": build_on, "earn": earn_on, "spend": True}.get(tab, True)
    return htmx_redirect(f"/plan?month={parse_month(month).strftime('%Y-%m')}&tab={tab if shown else 'spend'}")
