"""Rupees are grouped in lakhs and crores (12,34,567.00); every other currency in thousands (1,234,567.00)."""

import pytest

from app.formatting import group_digits, grouping_for, money


@pytest.mark.parametrize(
    ("value", "indian", "western"),
    [
        ("0", "0.00", "0.00"),
        ("999", "999.00", "999.00"),
        ("1000", "1,000.00", "1,000.00"),
        ("99999.5", "99,999.50", "99,999.50"),
        ("100000", "1,00,000.00", "100,000.00"),
        ("1234567", "12,34,567.00", "1,234,567.00"),
        ("123456789", "12,34,56,789.00", "123,456,789.00"),
        ("-1234567.891", "−12,34,567.891", "−1,234,567.891"),
    ],
)
def test_the_two_ways_of_grouping(value, indian, western):
    assert money(value, "indian") == indian and money(value, "western") == western


def test_only_the_rupee_is_grouped_in_lakhs():
    assert grouping_for("INR") == "indian"
    assert all(grouping_for(code) == "western" for code in ("USD", "EUR", "JPY", "PKR", None))
    assert group_digits("12345678", "indian") == "1,23,45,678"
