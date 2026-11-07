"""Splitting an amount among people: exact to the last unit, the same every time."""

from decimal import Decimal as D

import pytest

from app.services.contact_errors import InvalidExpenseAllocationError
from app.services.splits import split


def test_equal_shares_add_up_and_the_extra_units_go_to_the_first():
    assert split(D("100"), "equal", [None] * 3, 2) == [D("33.34"), D("33.33"), D("33.33")]
    assert split(D("0.05"), "equal", [None] * 3, 2) == [D("0.02"), D("0.02"), D("0.01")]
    assert split(D("1"), "equal", [None] * 3, 0) == [D("1"), D("0"), D("0")], "yen has no decimals"
    assert split(D("1.000"), "equal", [None] * 3, 3) == [D("0.334"), D("0.333"), D("0.333")]
    assert split(D("1500"), "equal", [None] * 3, 2) == [D("500.00")] * 3


def test_shares_are_weights():
    assert split(D("1500"), "shares", [D(1), D(2), D(2)], 2) == [D("300.00"), D("600.00"), D("600.00")]
    assert split(D("10"), "shares", [D(1), D(1), D(1)], 2) == [D("3.34"), D("3.33"), D("3.33")]
    assert split(D("100"), "shares", [D(0), D(1)], 2) == [D("0.00"), D("100.00")], "a zero weight pays nothing"
    with pytest.raises(InvalidExpenseAllocationError):
        split(D("100"), "shares", [D(0), D(0)], 2)


def test_percentages_must_make_a_hundred():
    assert split(D("100"), "percentage", [D("33.33"), D("33.33"), D("33.34")], 2) == [
        D("33.33"),
        D("33.33"),
        D("33.34"),
    ]
    assert split(D("200"), "percentage", [D(25), D(75)], 2) == [D("50.00"), D("150.00")]
    assert sum(split(D("0.07"), "percentage", [D(50), D(30), D(20)], 2)) == D("0.07")
    with pytest.raises(InvalidExpenseAllocationError, match="not 100"):
        split(D("100"), "percentage", [D(50), D(40)], 2)


def test_exact_amounts_must_make_the_total():
    assert split(D("100"), "exact", [D("60"), D("40")], 2) == [D("60"), D("40")]
    with pytest.raises(InvalidExpenseAllocationError, match="not the total"):
        split(D("100"), "exact", [D("60"), D("30")], 2)
    with pytest.raises(InvalidExpenseAllocationError, match="decimal places"):
        split(D("100"), "exact", [D("60.005"), D("39.995")], 2)


def test_bad_input_is_refused():
    with pytest.raises(InvalidExpenseAllocationError):
        split(D("100"), "shares", [D(1), None], 2)
    with pytest.raises(InvalidExpenseAllocationError):
        split(D("100"), "shares", [D(-1), D(2)], 2)
    with pytest.raises(InvalidExpenseAllocationError):
        split(D("100"), "equal", [], 2)
    with pytest.raises(InvalidExpenseAllocationError):
        split(D("100"), "random", [D(1)], 2)


@pytest.mark.parametrize("total", ["0.01", "1", "99.99", "1234567.89"])
@pytest.mark.parametrize("people", [2, 3, 7, 13])
def test_any_equal_split_adds_up(total, people):
    shares = split(D(total), "equal", [None] * people, 2)
    assert sum(shares) == D(total) and max(shares) - min(shares) <= D("0.01")
