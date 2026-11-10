"""Splitting an amount among people: pure arithmetic, no database.

Money never goes through binary floating point. Amounts are cut to the currency's decimals with the largest-remainder
method, so the shares always add up to the total exactly and the same input always gives the same answer: the leftover
units go to the biggest fractions first, and to the earlier participant when they tie."""

from collections.abc import Sequence
from decimal import ROUND_DOWN, Decimal

from .contact_errors import InvalidExpenseAllocationError

HUNDRED = Decimal(100)


def _unit(places: int) -> Decimal:
    return Decimal(1).scaleb(-places)


def _weighted(total: Decimal, weights: Sequence[Decimal], places: int) -> list[Decimal]:
    """`total` divided in proportion to `weights` (not all zero), to `places` decimals, adding up to `total`."""
    unit = _unit(places)
    weight_sum = sum(weights, Decimal(0))
    raw = [total * w / weight_sum for w in weights]
    shares = [r.quantize(unit, rounding=ROUND_DOWN) for r in raw]
    spare = int((total - sum(shares, Decimal(0))) / unit)
    by_fraction = sorted(range(len(raw)), key=lambda i: (-(raw[i] - shares[i]), i))
    for i in by_fraction[:spare]:
        shares[i] += unit
    return shares


def split(total: Decimal, method: str, values: Sequence[Decimal | None], places: int) -> list[Decimal]:
    """Each participant's share, in order. `values` are what the method needs: nothing for `equal`, the weights for
    `shares`, the percentages for `percentage` (they must make 100) and the amounts for `exact` (they must make the
    total)."""
    count = len(values)
    if count == 0:
        raise InvalidExpenseAllocationError("a shared expense needs participants!")
    unit = _unit(places)
    if method == "equal":
        return _weighted(total, [Decimal(1)] * count, places)
    given = [v for v in values if v is not None]
    if len(given) != count:
        raise InvalidExpenseAllocationError(f"every participant needs a value for a split by {method}!")
    if any(v < 0 for v in given):
        raise InvalidExpenseAllocationError("a share cannot be negative!")
    if method == "shares":
        if sum(given, Decimal(0)) == 0:
            raise InvalidExpenseAllocationError("at least one participant needs a share above zero!")
        return _weighted(total, given, places)
    if method == "percentage":
        if sum(given, Decimal(0)) != HUNDRED:
            raise InvalidExpenseAllocationError(f"the percentages add up to {sum(given, Decimal(0)):f}, not 100!")
        return _weighted(total, given, places)
    if method == "exact":
        if any(v != v.quantize(unit) for v in given):
            raise InvalidExpenseAllocationError(f"amounts can have at most {places} decimal places!")
        if sum(given, Decimal(0)) != total:
            raise InvalidExpenseAllocationError(
                f"the amounts add up to {sum(given, Decimal(0)):f}, not the total {total:f}!"
            )
        return list(given)
    raise InvalidExpenseAllocationError(f"unknown way to split: '{method}'!")
