"""How an amount is written for a person: grouped the way their currency is written (lakhs and crores for rupees,
thousands otherwise), with at least two decimals and a true minus sign. The views use it for the few sentences the
server words itself (a hint such as "of 2,50,000.00"); the app formats every other amount itself (lib/money.ts), and
tests/format_cases.json holds the two to the same answers."""

from decimal import Decimal

from .models.utils import normalize_amount


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


def money(value: Decimal | str | None, style: str) -> str:
    """Grouped digits and at least two decimals; coins and fund units keep their extra places."""
    if value is None:
        return ""
    text = format(normalize_amount(Decimal(value)), "f")
    sign = ""
    if text.startswith("-"):
        # A true minus sign lines up with "+" and reads better than a hyphen.
        sign, text = "−", text[1:]
    whole, dot, fraction = text.partition(".")
    return f"{sign}{group_digits(whole, style)}{dot}{fraction}"
