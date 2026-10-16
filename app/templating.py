import hashlib
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from fastapi.templating import Jinja2Templates

from .flash import flash_message
from .models.utils import normalize_amount
from .clock import local_today


BASE_DIR = Path(__file__).parent


def money(value: Decimal | str | None) -> str:
    """Thousands separators and at least two decimals; coins and fund units keep their extra places."""
    if value is None:
        return ""
    # A true minus sign lines up with "+" and reads better than a hyphen.
    return format(normalize_amount(Decimal(value)), ",f").replace("-", "\u2212")


SYMBOLS = {"INR": "\u20b9"}


def symbol(code: str | None) -> str:
    """The sign people write for a currency (the rupee sign for INR), else its code."""
    return SYMBOLS.get(code or "", code or "")


def amount(text: str, code: str | None) -> str:
    """An amount with its currency: the sign in front where there is one (₹1,200.00, −₹5.00), else the code after it."""
    if not code:
        return text
    sign = SYMBOLS.get(code)
    if sign is None:
        return f"{text} {code}"
    return f"\u2212{sign}{text[1:]}" if text.startswith("\u2212") else f"{sign}{text}"


def with_unit(text: str, code: str | None, default: str | None) -> str:
    """Add what the amount is in, unless it is in the currency everything is reported in."""
    return amount(text, code) if code and code != default else text


@lru_cache
def asset_url(path: str) -> str:
    """URL of a static file stamped with its content hash.

    A new deploy changes the hash, so browsers (Safari especially) can cache
    assets for a long time without ever showing a stale stylesheet.
    """
    digest = hashlib.sha256((BASE_DIR / "static" / path).read_bytes()).hexdigest()[:12]
    return f"/static/{path}?v={digest}"


def friendly_date(value: date) -> str:
    """Today / Yesterday / Mon, 28 Sep / 28 Sep 2025."""
    today = local_today()
    if value == today:
        return "Today"
    if value == today - timedelta(days=1):
        return "Yesterday"
    if value.year == today.year:
        return f"{value:%a}, {value.day} {value:%b}"
    return f"{value.day} {value:%b %Y}"


def origin_label(origin: str | None) -> str | None:
    """Who entered or changed a transaction, for people: "Claude (AI assistant)", "an import"."""
    if not origin:
        return None
    if origin.startswith("mcp:"):
        return f"{origin[4:]} (AI assistant)"
    return {"web": "the app", "api": "the API", "import": "an import", "recurring": "a recurring transaction"}.get(origin, origin)


templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["money"] = money
templates.env.filters["with_unit"] = with_unit
templates.env.filters["symbol"] = symbol
templates.env.filters["amount"] = amount
templates.env.filters["friendly_date"] = friendly_date
templates.env.filters["origin_label"] = origin_label
templates.env.globals["flash_message"] = flash_message
templates.env.globals["asset_url"] = asset_url
