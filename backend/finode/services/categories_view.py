"""What the Categories page and a category's own page show: for one kind (spending or earning), what each category came
to in a month, ranked, with its share; for one category, its month and its entries. The finode app's views
(/api/views/categories) read from here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ..schemas.category import CategoryRead
from .category import CategoryService
from .report import ReportService
from .transaction_rows import RegisterRow, category_register_row

# The chips on the Categories page, and the kind each one shows.
TABS = {"expense": "spending", "income": "earning"}
ZERO = Decimal("0.00")


def share(total: Decimal, grand: Decimal) -> str:
    """What part of the month's total a category is: '34%', '<1%', '0%' for one with nothing in the month (so every row
    has one), or nothing when the categories cancel out to no total at all."""
    if not total:
        return "0%"
    if not grand:
        return ""
    percent = abs(total) / abs(grand) * 100
    return "<1%" if percent < 1 else f"{round(percent)}%"


@dataclass
class CategoryRow:
    """One row of the Categories page: a category, its month and its share of the month."""

    category: CategoryRead
    total: Decimal
    share: str


def categories_page(
    categories: CategoryService, reports: ReportService, kind: str, when: date, end: date
) -> tuple[list[CategoryRow], Decimal]:
    """The page's rows, biggest first (a closed category only with something in the month), and the month's total."""
    own = reports.category_totals(kind, when, end)
    shown = [
        c for c in categories.list(kind, include_closed=True) if c.closed_on is None or own.get(c.id, ZERO) != ZERO
    ]
    grand = sum((own.get(c.id, ZERO) for c in shown), ZERO)
    ranked = sorted(shown, key=lambda c: (-abs(own.get(c.id, ZERO)), c.name.lower()))
    return [CategoryRow(c, own.get(c.id, ZERO), share(own.get(c.id, ZERO), grand)) for c in ranked], grand


@dataclass
class CategoryPage:
    category: CategoryRead
    # The category's month.
    total: Decimal
    # What was labelled with it, newest first.
    entries: list[RegisterRow]

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
    entries = [e for e in categories.register(category_id) if when <= e.date <= end]
    earning = category.kind == "earning"
    return CategoryPage(
        category=category,
        total=sum((e.change for e in entries), ZERO),
        entries=[category_register_row(e, earning) for e in reversed(entries)],
    )


@dataclass
class CategoryForm:
    category: CategoryRead | None  # the category being edited
    kind: str


def category_form(categories: CategoryService, category_id: UUID | None = None, root: str = "expense") -> CategoryForm:
    """The form for a category: editing one, or a new one (a spending one by default, an earning one from the Earning
    chip). LookupError for a category that is not the person's."""
    if category_id is None:
        return CategoryForm(category=None, kind=TABS.get(root.lower(), "spending"))
    current = categories.read(category_id)
    if current is None:
        raise LookupError("category not found")
    return CategoryForm(category=current, kind=current.kind)
