"""The dates of a card's bill: pure calendar arithmetic, like services/schedule.py (no database, no clock).

A card closes a bill on its *statement day* each month and wants it paid by its *due day*. Day 31 means the last day of a
shorter month. The due day follows the statement: when it is later in the month than the statement day it falls in the
same month, otherwise (a statement on the 22nd, due on the 15th) in the next one.
"""

import calendar
from datetime import date

# A bill is "due soon" (amber on the card's page, a reminder in the bell) this many days before its due date.
DUE_SOON_DAYS = 5


def _on(year: int, month: int, day: int) -> date:
    """The day of a month, or its last day when the month is shorter."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _shift(year: int, month: int, months: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def last_statement(statement_day: int, today: date) -> date:
    """The most recent statement date on or before `today`."""
    this_month = _on(today.year, today.month, statement_day)
    if this_month <= today:
        return this_month
    year, month = _shift(today.year, today.month, -1)
    return _on(year, month, statement_day)


def next_statement(statement_day: int, today: date) -> date:
    """The first statement date after `today`."""
    last = last_statement(statement_day, today)
    year, month = _shift(last.year, last.month, 1)
    return _on(year, month, statement_day)


def due_date(statement: date, statement_day: int, due_day: int) -> date:
    """When the bill closed on `statement` must be paid."""
    months = 0 if due_day > statement_day else 1
    year, month = _shift(statement.year, statement.month, months)
    return _on(year, month, due_day)
