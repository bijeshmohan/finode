"""What the Coming up list shows: what is coming up for the budget (services/coming_up.py) by day, each row with its
title and quiet second line, and a day's total when it adds up. The web page (routers/web/coming_up.py) and the finode
app's view (/api/views/coming-up) both read from here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from ..schemas.coming_up import ComingUpItem, ComingUpLine, ComingUpRead
from .account import AccountService
from .category import CategoryService
from .coming_up import ComingUpService
from .transaction_rows import AccountIndex


@dataclass
class ComingRow:
    item: ComingUpItem
    title: str
    sub: str


@dataclass
class ComingDay:
    date: date
    rows: list[ComingRow] = field(default_factory=list)
    # What the day comes to, only when every row goes one way and there is more than one.
    total: Decimal | None = None


@dataclass
class ComingDays:
    data: ComingUpRead
    days: list[ComingDay]


def coming_days(
    service: ComingUpService, accounts: AccountService, categories: CategoryService, through: date | None = None
) -> ComingDays:
    data = service.view(through)
    index = AccountIndex.build(accounts.list(), categories.list(include_closed=True))

    def names(lines: list[ComingUpLine]) -> list[str]:
        found: list[str] = []
        for line in lines:
            name = index.line_name(line)
            if name not in found:
                found.append(name)
        return found

    def row(item: ComingUpItem) -> ComingRow:
        debits, credits = names(item.debits), names(item.credits)
        return ComingRow(
            item=item,
            title=item.payee or ", ".join(debits),
            sub=f"{', '.join(credits)} → {', '.join(debits)}" if item.payee else ", ".join(credits),
        )

    days: list[ComingDay] = []
    for item in data.items:
        if not days or days[-1].date != item.date:
            days.append(ComingDay(item.date))
        days[-1].rows.append(row(item))
    for day in days:
        one_way = len({r.item.income for r in day.rows}) == 1
        if one_way and len(day.rows) > 1:
            day.total = sum((r.item.amount for r in day.rows), Decimal(0))
    return ComingDays(data, days)
