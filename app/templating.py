from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.templating import Jinja2Templates


BASE_DIR = Path(__file__).parent


def money(value: Decimal | str | None) -> str:
    if value is None:
        return ""
    return format(Decimal(value), ",.2f")


def friendly_date(value: date) -> str:
    """Today / Yesterday / Mon, 28 Sep / 28 Sep 2025."""
    today = date.today()
    if value == today:
        return "Today"
    if value == today - timedelta(days=1):
        return "Yesterday"
    if value.year == today.year:
        return f"{value:%a}, {value.day} {value:%b}"
    return f"{value.day} {value:%b %Y}"


templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["money"] = money
templates.env.filters["friendly_date"] = friendly_date
