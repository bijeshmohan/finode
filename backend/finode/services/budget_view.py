"""What the Budgets page shows: the month's categories as one ranked list with a bar each and how each row reads. The
finode app's views (/api/views/budget) read from here."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

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


def by_assigned(lines: list[BudgetLine]) -> list[BudgetLine]:
    """Biggest budget first, then by name."""
    return sorted(lines, key=lambda ln: (-ln.assigned, ln.name.lower()))


def hint(line: BudgetLine, money: Money) -> str:
    """The small line under a category's name: what needs a look (last month's overspending). `money` writes an amount
    as the person's currency is written."""
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
class Row:
    line: BudgetLine
    hint: str
    reading: Reading


@dataclass
class BudgetPage:
    budget: BudgetRead
    month: date
    rows: list[Row]
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
    current = data.month == month_start(None)
    return BudgetPage(
        budget=data,
        month=data.month,
        rows=[Row(ln, hint(ln, money), reading(ln)) for ln in by_assigned(data.lines)],
        show_intro=not budget.started(),
        overspent=-data.available if data.available < 0 else ZERO,
        is_current=current,
        pace=month_progress() if current else None,
    )
