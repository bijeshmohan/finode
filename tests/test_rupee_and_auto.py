"""The rupee sign in place of "INR", and violet for what was added automatically."""

from app.templating import amount, symbol


def test_the_rupee_sign_goes_in_front_and_other_currencies_keep_their_code():
    assert symbol("INR") == "\u20b9" and symbol("USD") == "USD" and symbol(None) == ""
    assert amount("1,200.00", "INR") == "\u20b91,200.00"
    assert amount("\u22125.00", "INR") == "\u20b9\u22125.00", (
        "a negative keeps its minus next to the digits, after the sign"
    )
    assert amount("40.00", "USD") == "40.00 USD"
