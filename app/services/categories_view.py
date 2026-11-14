"""What the Categories page and a category's own page show: for one kind (spending or earning), what each category came
to in a month, ranked, with what is inside it and its share; for one category, its month, its subcategories and its own
entries. The web pages (routers/web/categories.py) and the finode app's views (/api/views/categories) both read from
here."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from ..schemas.category import CategoryRead
from .category import CategoryService
from .report import ReportService
from .transaction_rows import RegisterRow, category_register_row

# The chips on the Categories page, and the kind each one shows.
TABS = {"expense": "spending", "income": "earning"}
KIND_TABS = {kind: tab for tab, kind in TABS.items()}
ZERO = Decimal("0.00")


@dataclass
class CatNode:
    """A category and the categories inside it (a group holds categories; a category holds none)."""

    category: CategoryRead
    children: list[CatNode] = field(default_factory=list)

    def walk(self) -> Iterator[CatNode]:
        yield self
        for child in self.children:
            yield from child.walk()


def category_tree(categories: CategoryService, kind: str, include_closed: bool = False) -> list[CatNode]:
    """The categories of one kind as groups with their categories inside, A to Z."""
    found = categories.list(kind, include_closed)
    nodes = {c.id: CatNode(c) for c in found}
    top: list[CatNode] = []
    for node in nodes.values():
        parent = nodes.get(node.category.parent_id) if node.category.parent_id else None
        (parent.children if parent is not None else top).append(node)
    for node in nodes.values():
        node.children.sort(key=lambda n: n.category.name.lower())
    top.sort(key=lambda n: n.category.name.lower())
    return top


def figures(
    categories: CategoryService, reports: ReportService, kind: str, when: date, end: date
) -> tuple[list[CatNode], dict[UUID, Decimal], dict[UUID, Decimal]]:
    """The month's amounts for one kind: (the tree with closed empty categories left out, what was labelled with each
    category itself, what each category and everything inside it came to)."""
    own = reports.category_totals(kind, when, end)
    top = category_tree(categories, kind, include_closed=True)
    totals: dict[UUID, Decimal] = {}

    def walk(node: CatNode) -> Decimal:
        total = own.get(node.category.id, ZERO) + sum((walk(child) for child in node.children), ZERO)
        totals[node.category.id] = total
        return total

    # A deleted (closed) category with nothing in the month is not listed, at either level.
    def shown(n: CatNode) -> bool:
        return n.category.closed_on is None or any(own.get(m.category.id) for m in n.walk())

    for n in top:
        n.children = [c for c in n.children if shown(c)]
    top = [n for n in top if shown(n)]
    for n in top:
        walk(n)
    return top, own, totals


def share(total: Decimal, grand: Decimal) -> str:
    """What part of the month's total a category is: '34%', '<1%', '0%' for one with nothing in the month (so every row
    has one), or nothing when the categories cancel out to no total at all."""
    if not total:
        return "0%"
    if not grand:
        return ""
    percent = abs(total) / abs(grand) * 100
    return "<1%" if percent < 1 else f"{round(percent)}%"


def by_amount(nodes: list[CatNode], totals: dict[UUID, Decimal]) -> list[CatNode]:
    return sorted(nodes, key=lambda n: (-abs(totals[n.category.id]), n.category.name.lower()))


@dataclass
class CategoryRow:
    """One row of the Categories page: a top-level category, its month, what is inside it ("Fuel · Taxi · +2") and its
    share of the month."""

    node: CatNode
    total: Decimal
    share: str
    hint: str


def categories_page(
    categories: CategoryService, reports: ReportService, kind: str, when: date, end: date
) -> tuple[list[CategoryRow], Decimal]:
    """The page's rows, biggest first, and the month's total."""
    top, _own, totals = figures(categories, reports, kind, when, end)
    grand = sum((totals[n.category.id] for n in top), ZERO)
    rows = []
    for n in by_amount(top, totals):
        total = totals[n.category.id]
        inside = [c.category.name for c in by_amount(n.children, totals) if totals[c.category.id]]
        hint = " · ".join(inside[:3] + ([f"+{len(inside) - 3}"] if len(inside) > 3 else []))
        rows.append(CategoryRow(n, total, share(total, grand), hint))
    return rows, grand


@dataclass
class CategoryPage:
    category: CategoryRead
    group: CategoryRead | None
    # The whole category's month (its subcategories too).
    total: Decimal
    # Its subcategories with their month, biggest first, and what was labelled with the category itself besides them.
    subs: list[tuple[CatNode, Decimal]]
    own_here: Decimal
    # What was labelled with this category itself, newest first (each subcategory's entries are on its own page).
    entries: list[RegisterRow]
    can_add_child: bool

    @property
    def new_transaction_url(self) -> str | None:
        """The "+" in the bar starts an entry for this category and comes back here (a closed one: none)."""
        if self.category.closed_on:
            return None
        return f"/transactions/new?category={self.category.id}&back=/categories/{self.category.id}"


def category_page(
    categories: CategoryService, reports: ReportService, category_id: UUID, when: date, end: date
) -> CategoryPage:
    """A category's own page for one month. LookupError for a category that is not the person's."""
    category = categories.read(category_id)
    if category is None:
        raise LookupError("category not found")

    def in_month(rows: list | None) -> list:
        return [e for e in (rows or []) if when <= e.date <= end]

    everything = in_month(categories.register(category_id))
    own_entries = in_month(categories.register(category_id, own_only=True))
    top, own, totals = figures(categories, reports, category.kind, when, end)
    shown = next((n for t in top for n in t.walk() if n.category.id == category_id), None)
    subs = [(c, totals[c.category.id]) for c in by_amount(shown.children, totals)] if shown is not None else []
    earning = category.kind == "earning"
    return CategoryPage(
        category=category,
        group=categories.read(category.parent_id) if category.parent_id else None,
        total=sum((e.change for e in everything), ZERO),
        subs=subs,
        own_here=own.get(category_id, ZERO) if subs else ZERO,
        entries=[category_register_row(e, earning) for e in reversed(own_entries)],
        can_add_child=category.parent_id is None and category.closed_on is None and category.system_key is None,
    )


@dataclass
class CategoryForm:
    category: CategoryRead | None  # the category being edited
    kind: str
    parent_id: UUID | None
    # The groups it can go under: none for a group that holds categories (two levels at most).
    groups: list[CategoryRead]


def category_form(
    categories: CategoryService,
    category_id: UUID | None = None,
    parent: UUID | None = None,
    root: str = "expense",
) -> CategoryForm:
    """The form for a category: editing one, or a new one (a spending one by default, an earning one from the Earning
    chip; opened from a group's page it starts inside that group, whose kind it takes). LookupError for a category or a
    group that is not the person's."""
    current = None
    if category_id is not None:
        current = categories.read(category_id)
        if current is None:
            raise LookupError("category not found")
        kind, parent = current.kind, current.parent_id
    else:
        kind = TABS.get(root.lower(), "spending")
        if parent is not None:
            group = categories.read(parent)
            if group is None:
                raise LookupError("category not found")
            kind = group.kind
    groups = [n.category for n in category_tree(categories, kind) if current is None or n.category.id != current.id]
    if current is not None and any(c.parent_id == current.id for c in categories.list(kind, True)):
        groups = []
    return CategoryForm(category=current, kind=kind, parent_id=parent, groups=groups)
