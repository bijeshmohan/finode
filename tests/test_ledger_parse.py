from datetime import date
from decimal import Decimal

from app.ledger import parse


def _errors(text: str) -> list[str]:
    return parse(text).errors


def test_parses_a_basic_transaction():
    journal = parse(
        "; a comment\n"
        "2026-10-04 * (12) DMart  ; weekly\n"
        "    ; groceries\n"
        "    Expenses:Food:Groceries      ₹1,250.00\n"
        "    Assets:Bank\n"
    )
    assert journal.errors == []
    [t] = journal.transactions
    assert t.date == date(2026, 10, 4) and t.payee == "DMart"
    assert t.notes == ["weekly", "groceries"]
    assert [(p.account, p.amount) for p in t.postings] == [
        ("Expenses:Food:Groceries", Decimal("1250.00")),
        ("Assets:Bank", Decimal("-1250.00")),
    ]


def test_accepts_slash_dates_tabs_and_suffix_symbols():
    journal = parse("2026/1/5\n\tAssets:Cash\t-10 INR\n\tExpenses:Misc\t10 INR\n")
    assert journal.errors == []
    assert journal.transactions[0].date == date(2026, 1, 5)
    assert journal.transactions[0].payee == ""


def test_account_directive_with_note():
    journal = parse("account Assets:Bank\n    note Main account\naccount Expenses:Food\n")
    assert [(a.name, a.note) for a in journal.accounts] == [("Assets:Bank", "Main account"), ("Expenses:Food", None)]


def test_ignored_directives_do_not_fail():
    text = "commodity ₹\n    format 1,000.00 ₹\nP 2026-01-01 USD 83 ₹\nD ₹1,000.00\npayee DMart\n"
    assert _errors(text) == []


def test_unbalanced_transaction_is_reported_with_line():
    errors = _errors("2026-10-04 x\n    Expenses:A  10\n    Assets:B  -5\n")
    assert errors == ["line 1: does not balance (off by 5.00)"]


def test_two_elided_amounts_rejected():
    errors = _errors("2026-10-04 x\n    Expenses:A\n    Assets:B\n")
    assert errors == ["line 3: only one posting may leave out its amount"]


def test_single_posting_rejected():
    assert _errors("2026-10-04 x\n    Expenses:A  10\n") == ["line 1: a transaction needs at least two postings"]


def test_mixed_currencies_rejected():
    errors = _errors("2026-10-04 x\n    A:B  10 USD\n    C:D  -10 EUR\n")
    assert errors and "mixes currencies" in errors[0]


def test_unsupported_features_are_reported():
    assert "virtual postings" in _errors("2026-10-04 x\n    (Assets:A)  10\n    Assets:B  -10\n")[0]
    assert "lots are not supported" in _errors("2026-10-04 x\n    Assets:A  10 AAPL {5 USD}\n    Assets:B  -50 USD\n")[0]
    assert "automated" in _errors("= expenses\n    (Assets:A)  1\n")[0]
    assert "unsupported directive 'include'" in _errors("include other.ledger\n")[0]
    assert "balance assignments" in _errors("2026-10-04 x\n    Assets:A  = 5\n    Assets:B\n")[0]
    assert "decimal mark" in _errors("decimal-mark ,\n")[0]


def test_too_many_decimals_and_bad_numbers():
    assert "more than 8 decimal places" in _errors("2026-10-04 x\n    A:B  1.123456789\n    C:D  -1.123456789\n")[0]
    assert "cannot read the amount" in _errors("2026-10-04 x\n    A:B  1.250,00\n    C:D  -1\n")[0]


def test_bad_date():
    assert _errors("2026-13-40 x\n    A:B  1\n    C:D\n") == ["line 1: not a valid date"]


def test_balance_assertion_checked_in_file_order():
    ok = "2026-01-01 a\n    Assets:Bank  100 = 100\n    Equity:Open\n"
    assert _errors(ok) == []
    bad = ok + "2026-01-02 b\n    Assets:Bank  50 = 200\n    Equity:Open\n"
    assert "balance assertion failed" in _errors(bad)[0]


def test_semicolon_inside_payee_is_not_a_comment():
    journal = parse("2026-01-01 AT;T\n    A:B  1\n    C:D\n")
    assert journal.transactions[0].payee == "AT;T"


# ---- several commodities ------------------------------------------------------------------------------------------


def _txn(text: str):
    journal = parse(text)
    assert journal.errors == [], journal.errors
    return journal.transactions[0]


def test_amounts_keep_their_commodity_and_precision():
    t = _txn("2026-01-05 x\n    Assets:Wise  100.50 USD\n    Assets:Coin  0.01234567 BTC\n    Equity:O  -100.50 USD\n    Equity:P  -0.01234567 BTC\n")
    assert [(p.amount, p.commodity) for p in t.postings] == [
        (Decimal("100.50"), "USD"),
        (Decimal("0.01234567"), "BTC"),
        (Decimal("-100.50"), "USD"),
        (Decimal("-0.01234567"), "BTC"),
    ]


def test_a_total_price_converts_a_posting():
    t = _txn("2026-01-05 Buy USD\n    Assets:Wise   100 USD @@ 8350 INR\n    Assets:HDFC   -8350 INR\n")
    wise, bank = t.postings
    assert (wise.amount, wise.commodity, wise.cost, wise.cost_commodity) == (Decimal("100"), "USD", Decimal("8350"), "INR")
    assert (bank.amount, bank.commodity, bank.cost) == (Decimal("-8350"), "INR", None)


def test_a_unit_price_is_multiplied_out():
    t = _txn("2026-01-05 Buy\n    Assets:Zerodha:INFY  10 INFY @ 1500 INR\n    Assets:HDFC\n")
    infy, bank = t.postings
    assert infy.cost == Decimal("15000") and infy.cost_commodity == "INR"
    assert (bank.amount, bank.commodity) == (Decimal("-15000"), "INR"), "the left-out amount is filled in"


def test_selling_has_a_negative_amount_and_a_positive_price():
    t = _txn("2026-01-05 Sell\n    Assets:Wise  -40 USD @@ 3400 INR\n    Assets:HDFC  3400 INR\n")
    assert t.postings[0].amount == Decimal("-40") and t.postings[0].cost == Decimal("3400")


def test_a_symbol_before_the_number_and_a_price_in_symbols():
    t = _txn("2026-01-05 x\n    Assets:Wise  $100 @@ ₹8,350\n    Assets:HDFC  -₹8,350\n")
    assert (t.postings[0].commodity, t.postings[0].cost_commodity) == ("$", "₹")


def test_commodities_without_a_price_are_explained():
    errors = _errors("2026-01-05 x\n    Assets:Wise  100 USD\n    Assets:HDFC  -8350 INR\n")
    assert len(errors) == 1 and errors[0].startswith("line 1: mixes currencies ('USD' and 'INR') without a price")
    assert "@@" in errors[0]


def test_a_wrong_price_does_not_balance():
    errors = _errors("2026-01-05 x\n    Assets:Wise  100 USD @@ 8300 INR\n    Assets:HDFC  -8350 INR\n")
    assert errors == ["line 1: does not balance (off by 50.00)"]


def test_an_amount_without_a_commodity_joins_the_only_one_in_the_transaction():
    assert _errors("2026-01-05 x\n    A:B  10 INR\n    C:D  -10\n") == []
    assert _errors("2026-01-05 x\n    A:B  10\n    C:D  -10 INR\n") == []


def test_only_one_left_out_amount_in_a_multi_commodity_transaction_may_be_inferred():
    assert _errors("2026-01-05 x\n    A:B  10 USD\n    C:D  5 EUR\n    E:F\n")[0].startswith("line 1: mixes currencies")


def test_prices_must_be_positive_and_need_an_amount():
    assert "a price must be positive" in _errors("2026-01-05 x\n    A:B  10 USD @@ -5 INR\n    C:D  5 INR\n")[0]
    assert "a price must be positive" in _errors("2026-01-05 x\n    A:B  10 USD @ 0 INR\n    C:D\n")[0]
    assert "a price needs an amount" in _errors("2026-01-05 x\n    A:B  @@ 5 INR\n    C:D  5 INR\n")[0]


def test_balance_assertions_are_per_commodity():
    ok = (
        "2026-01-01 a\n    Assets:Wise  100 USD = 100 USD\n    Equity:O  -100 USD\n"
        "2026-01-02 b\n    Assets:Wise  50 EUR = 50 EUR\n    Equity:O  -50 EUR\n"
    )
    assert _errors(ok) == []
    bad = ok + "2026-01-03 c\n    Assets:Wise  10 USD = 111 USD\n    Equity:O  -10 USD\n"
    assert "balance assertion failed: 'Assets:Wise' is 110.00, expected 111.00" in _errors(bad)[0]


def test_commodity_directives_carry_decimals_and_finodes_tags():
    journal = parse(
        "commodity 1,000.00 INR\n"
        "commodity INFY  ; name:Infosys, kind:stock\n"
        "commodity 0.000 NIFTYBEES\n"
        "commodity BTC\n    format 1,000.00000000 BTC\n"
    )
    assert journal.errors == []
    got = {c.symbol: (c.decimals, c.name, c.kind) for c in journal.commodities}
    assert got == {
        "INR": (2, None, None),
        "INFY": (None, "Infosys", "stock"),
        "NIFTYBEES": (3, None, None),
        "BTC": (8, None, None),
    }


def test_price_directives_are_read():
    journal = parse("P 2026-01-05 USD 83.5 INR\nP 2026/01/06 00:00:00 \"HDFC.BO\" $1,650.25\n")
    assert journal.errors == []
    assert [(p.date, p.symbol, p.price, p.quote) for p in journal.prices] == [
        (date(2026, 1, 5), "USD", Decimal("83.5"), "INR"),
        (date(2026, 1, 6), "HDFC.BO", Decimal("1650.25"), "$"),
    ]


def test_bad_price_and_commodity_directives():
    assert _errors("P nonsense\n") == ["line 1: cannot read the price line"]
    assert _errors("P 2026-13-40 USD 5 INR\n") == ["line 1: not a valid date"]
    assert _errors("P 2026-01-05 USD 0 INR\n") == ["line 1: a price must be positive"]
    assert _errors("commodity 1,000.00\n")[0].startswith("line 1:")
