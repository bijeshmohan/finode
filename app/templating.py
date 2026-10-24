"""The Jinja2 environment and its filters: money (with Indian or western digit grouping), currency signs, friendly dates, hashed static URLs."""

import hashlib
from contextvars import ContextVar
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from fastapi.templating import Jinja2Templates

from .clock import local_day, local_today
from .currencies import find
from .flash import flash_message, flash_undo
from .models.utils import normalize_amount

BASE_DIR = Path(__file__).parent


# How the whole part of an amount is grouped: thousands (1,234,567.00) or, for rupees, lakhs and crores (12,34,567.00).
_grouping: ContextVar[str] = ContextVar("grouping", default="western")
_places: ContextVar[int] = ContextVar("places", default=2)


def grouping_for(code: str | None) -> str:
    """Rupees are written in lakhs and crores; every other currency in thousands."""
    return "indian" if code == "INR" else "western"


def group_digits(digits: str, style: str) -> str:
    """Put commas into a run of digits: 1,234,567 (western) or 12,34,567 (indian)."""
    if style == "indian" and len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        pairs: list[str] = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        return ",".join(([head] if head else []) + pairs + [tail])
    return f"{int(digits):,}" if digits.isdigit() else digits


def money(value: Decimal | str | None, style: str | None = None) -> str:
    """Grouped digits and at least two decimals; coins and fund units keep their extra places.
    The grouping follows the person's currency (see `grouping_for`) unless a style is given."""
    if value is None:
        return ""
    text = format(normalize_amount(Decimal(value)), "f")
    sign = ""
    if text.startswith("-"):
        # A true minus sign lines up with "+" and reads better than a hyphen.
        sign, text = "\u2212", text[1:]
    whole, dot, fraction = text.partition(".")
    return f"{sign}{group_digits(whole, style or _grouping.get())}{dot}{fraction}"


SYMBOLS = {"INR": "\u20b9"}


def symbol(code: str | None) -> str:
    """The sign people write for a currency (the rupee sign for INR), else its code."""
    return SYMBOLS.get(code or "", code or "")


def places(code: str | None) -> int:
    """How many decimals the currency keeps (rupees 2, yen 0): the quick-amount chips never go finer."""
    found = find(code)
    return found.decimals if found else 2


def amount(text: str, code: str | None) -> str:
    """An amount with its currency: the sign in front where there is one (₹1,200.00, −₹5.00), else the code after it."""
    if not code:
        return text
    sign = SYMBOLS.get(code)
    if sign is None:
        return f"{text} {code}"
    return f"\u2212{sign}{text[1:]}" if text.startswith("\u2212") else f"{sign}{text}"


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


def date_chip(value) -> str:
    """The day on the Add screen's date chip: Today, 24 Oct / Wed, 21 Oct / 21 Oct 2025."""
    if isinstance(value, str):
        value = date.fromisoformat(value)
    today = local_today()
    if value == today:
        return f"Today, {value.day} {value:%b}"
    if value.year == today.year:
        return f"{value:%a}, {value.day} {value:%b}"
    return f"{value.day} {value:%b %Y}"


def origin_label(origin: str | None) -> str | None:
    """Who entered or changed a transaction, for people: "Claude (AI assistant)", "an import"."""
    if not origin:
        return None
    if origin.startswith("mcp:"):
        return f"{origin[4:]} (AI assistant)"
    return {"web": "the app", "api": "the API", "import": "an import", "recurring": "a recurring transaction"}.get(
        origin, origin
    )


templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["money"] = money
templates.env.globals["grouping"] = lambda: _grouping.get()
templates.env.globals["decimals"] = lambda: _places.get()
templates.env.filters["symbol"] = symbol
templates.env.filters["amount"] = amount
templates.env.filters["friendly_date"] = friendly_date
templates.env.filters["date_chip"] = date_chip
templates.env.filters["local_day"] = local_day
templates.env.filters["origin_label"] = origin_label
templates.env.globals["flash_message"] = flash_message
templates.env.globals["flash_undo"] = flash_undo
templates.env.globals["asset_url"] = asset_url


# A page is rendered inside TemplateResponse, in the thread that handled the request, so the person's grouping can be
# set around it from what the request loaded (`request.state.currency`, see dependencies.load_currency).
_render = templates.TemplateResponse


def _template_response(request, *args, **kwargs):
    code = getattr(request.state, "currency", None)
    token, places_token = _grouping.set(grouping_for(code)), _places.set(places(code))
    try:
        return _render(request, *args, **kwargs)
    finally:
        _grouping.reset(token)
        _places.reset(places_token)


# Deliberate: every render sets the grouping style first (see _template_response).
templates.TemplateResponse = _template_response  # type: ignore[method-assign]
