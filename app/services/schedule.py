"""When a recurring rule falls due. Pure date arithmetic, no database."""

import calendar
from datetime import date, timedelta

from ..models.recurring import Frequency


def occurrence(start: date, frequency: str, every: int, n: int) -> date:
    """The n-th occurrence (0 is the start date). Months and years keep the start's day, clamped to short
    months: a rule starting on 31 January falls on 28 or 29 February, then 31 March again."""
    if frequency == Frequency.DAILY:
        return start + timedelta(days=n * every)
    if frequency == Frequency.WEEKLY:
        return start + timedelta(weeks=n * every)
    months = n * every * (12 if frequency == Frequency.YEARLY else 1)
    year, month = divmod(start.year * 12 + start.month - 1 + months, 12)
    month += 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def first_on_or_after(start: date, frequency: str, every: int, day: date) -> date:
    """The first occurrence that is `day` or later (the start date itself if that is already later)."""
    n = 0
    if day > start:
        # Jump close, then walk: the estimate is never past the answer.
        span = (day - start).days
        unit = {Frequency.DAILY: 1, Frequency.WEEKLY: 7, Frequency.MONTHLY: 31, Frequency.YEARLY: 366}[frequency]
        n = max(0, span // (unit * every) - 1)
    while (found := occurrence(start, frequency, every, n)) < day:
        n += 1
    return found


def first_after(start: date, frequency: str, every: int, day: date) -> date:
    return first_on_or_after(start, frequency, every, day + timedelta(days=1))


def describe(frequency: str, every: int) -> str:
    """"Every month", "Every 2 weeks"."""
    unit = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}[frequency]
    return f"Every {unit}" if every == 1 else f"Every {every} {unit}s"
