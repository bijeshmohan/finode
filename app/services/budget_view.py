"""What the Budgets pages show: the month's categories as a ranked list with a bar each, how each row reads, a group's
glance and its categories, and the categories money can move between. The finode app's
views (/api/views/budget) read from here."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ..clock import month_progress
from ..schemas.budget import BudgetLine, BudgetRead
from .budget import BudgetService, month_start

ZERO = Decimal("0.00")

# How an amount is written in the person's currency (formatting.money with their grouping).
Money = Callable[[Decimal], str]


def parse_month(value: str) -> date:
    """'2026-10' (or any date) -> the first day of that month; the current month when empty or unreadable."""
    value = (value or "").strip()
    try:
        if len(value) == 7:
            return month_start(date.fromisoformat(value + "-01"))
        return month_start(date.fromisoformat(value)) if value else month_start(None)
    except ValueError:
        return month_start(None)


class Node:
    """A category in the budget: a group (with its subcategories, and its own 'everything else' line) or a plain category.
    Categories go two levels deep, so a subcategory is never a group itself."""

    def __init__(self, line: BudgetLine):
        self.line = line
        self.children: list[Node] = []
        self.other: BudgetLine | None = None

    @property
    def is_group(self) -> bool:
        return bool(self.children)

    def lines(self) -> list[BudgetLine]:
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
    return BudgetLine(
        category_id=group.category_id,
        name=f"{group.name} (other)",
        path=group.path,
        depth=group.depth + 1,
        assigned=ZERO,
        activity=ZERO,
        available=ZERO,
        overspent_last_month=ZERO,
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


def by_assigned(nodes: list[Node]) -> list[Node]:
    """Biggest budget first, then by name."""
    return sorted(nodes, key=lambda n: (-n.line.assigned, n.line.name.lower()))


def hint(node: Node, money: Money) -> str:
    """The small line under a category's name: the three biggest things inside a group and '+N'; for a plain category
    what needs a look (last month's overspending). `money` writes an amount as the person's currency is written."""
    if node.is_group:
        inside = [c.line.name for c in by_assigned(node.children) if c.line.assigned or c.line.activity] or [
            c.line.name for c in node.children
        ]
        return " · ".join(inside[:3] + ([f"+{len(inside) - 3}"] if len(inside) > 3 else []))
    line = node.line
    if line.overspent_last_month:
        return f"{money(line.overspent_last_month)} overspent last month"
    return ""


@dataclass
class Reading:
    """How a row reads: "of 25,000.00" or "nothing assigned", whether it is overspent or all spent, and
    how far its bar runs."""

    of: Decimal | None
    state: Literal["overspent", "all_spent"] | None
    percent: int
    over: bool


def reading(line: BudgetLine) -> Reading:
    total = line.activity + line.available
    if line.assigned or line.available or line.activity:
        of: Decimal | None = total if total > 0 else line.activity
    else:
        of = None
    state: Literal["overspent", "all_spent"] | None = None
    if line.available < 0:
        state = "overspent"
    elif line.available == 0 and line.activity > 0:
        state = "all_spent"
    over = line.available < 0
    percent = 100 if over else (int(round(line.activity / total * 100, 0)) if total > 0 else 0)
    return Reading(of, state, percent, over)


@dataclass
class Glance:
    """The month (or a group) at a glance, worked out as Home does: what is left, and what was spent out of what there
    was to spend."""

    left: Decimal
    spent: Decimal
    of: Decimal
    percent: int
    planned: bool


def glance(data: BudgetLine) -> Glance:
    to_spend = data.activity + max(data.available, Decimal(0))
    return Glance(
        left=data.available,
        spent=data.activity,
        of=to_spend,
        percent=int(min(max(data.activity / to_spend, Decimal(0)), Decimal(1)) * 100) if to_spend > 0 else 0,
        planned=data.assigned > 0 or data.available > 0,
    )


@dataclass
class Row:
    node: Node
    hint: str
    reading: Reading
    unused: bool = False


@dataclass
class BudgetPage:
    budget: BudgetRead
    month: date
    tree: list[Node]
    rows: list[Row]
    unused_count: int
    # A short welcome until the first amount is assigned.
    show_intro: bool
    # More spent than there was to spend in all the categories together.
    overspent: Decimal
    is_current: bool
    # Only the current month has a "today": the tick on the bars shows how far through it we are.
    pace: int | None

    @property
    def month_name(self) -> str:
        return f"{calendar.month_name[self.month.month]} {self.month.year}"


def budget_page(budget: BudgetService, month: date, money: Money) -> BudgetPage:
    data = budget.view(month)
    tree = build_tree(data.lines)
    # Whole groups with nothing in them (nothing assigned, spent or planned) are tucked away once anything is in use;
    # plain top-level categories always show, so there is always something to tap and assign to.
    unused = {n.line.category_id for n in tree if n.is_group and not n.used} if any(n.used for n in tree) else set()
    current = data.month == month_start(None)
    return BudgetPage(
        budget=data,
        month=data.month,
        tree=tree,
        rows=[Row(n, hint(n, money), reading(n.line), n.line.category_id in unused) for n in by_assigned(tree)],
        unused_count=len(unused),
        show_intro=not budget.started(),
        overspent=-data.available if data.available < 0 else ZERO,
        is_current=current,
        pace=month_progress() if current else None,
    )


@dataclass
class GroupPage:
    page: BudgetPage
    group: Node
    kids: list[Row]
    glance: Glance
    minimum: Decimal


def group_page(budget: BudgetService, month: date, category_id: UUID, money: Money) -> GroupPage:
    """One group of the budget for a month. LookupError for a category that is not a group of the person's."""
    page = budget_page(budget, month, money)
    node = next((n for n in page.tree if n.line.category_id == category_id and n.is_group), None)
    if node is None:
        raise LookupError("category not found")
    return GroupPage(
        page=page,
        group=node,
        kids=[Row(c, hint(c, money), reading(c.line)) for c in by_assigned(node.children)],
        glance=glance(node.line),
        minimum=budget.group_minimum(month, category_id, page.budget),
    )


def move_lines(data: BudgetRead) -> list[BudgetLine]:
    """The categories money can move between: every category line, never a group's total."""
    return [line for line in data.lines if not line.group]
