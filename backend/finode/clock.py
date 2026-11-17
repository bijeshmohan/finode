"""What day it is. The server's own clock decides unless FINODE_TIMEZONE names a zone (for example
Asia/Kolkata), so "today" is the day where the people using it live and not where the server is."""

from datetime import UTC, date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from .config import settings

# The days finode accepts for entries, rules, targets and months. Far wider than any real use, narrow enough that
# date arithmetic (the next month, the day before) can never run off the calendar's ends at year 1 or 9999.
FIRST_DAY = date(1900, 1, 1)
LAST_DAY = date(2999, 12, 31)


@lru_cache
def _zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_now() -> datetime:
    return datetime.now(_zone(settings.timezone)) if settings.timezone else datetime.now().astimezone()


def local_today() -> date:
    return local_now().date()


def local_midnight_utc() -> datetime:
    """The start of today, as a UTC moment (to compare with stored timestamps)."""
    return local_now().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def month_progress(today: date | None = None) -> int:
    """How far through its month a day is, as a whole percentage (the 15th of a 30-day month is 50)."""
    from calendar import monthrange

    day = today or local_today()
    return round(100 * day.day / monthrange(day.year, day.month)[1])
