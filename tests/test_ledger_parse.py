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
    text = "commodity ₹\n    format 1,000.00 ₹\nD ₹1,000.00\npayee DMart\n"
    assert _errors(text) == []


def test_unbalanced_transaction_is_reported_with_line():
    errors = _errors("2026-10-04 x\n    Expenses:A  10\n    Assets:B  -5\n")
    assert errors == ["line 1: does not balance (off by 5.00)"]


def test_two_elided_amounts_rejected():
    errors = _errors("2026-10-04 x\n    Expenses:A\n    Assets:B\n")
    assert errors == ["line 3: only one posting may leave out its amount"]


def test_single_posting_rejected():
    assert _errors("2026-10-04 x\n    Expenses:A  10\n") == ["line 1: a transaction needs at least two postings"]


def test_unsupported_features_are_reported():
    assert "virtual postings" in _errors("2026-10-04 x\n    (Assets:A)  10\n    Assets:B  -10\n")[0]
    assert (
        "lots are not supported" in _errors("2026-10-04 x\n    Assets:A  10 AAPL {5 USD}\n    Assets:B  -50 USD\n")[0]
    )
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


# ---- one currency, with or without a label on the amounts ----------------------------------------------------------


def _txn(text: str):
    journal = parse(text)
    assert journal.errors == [], journal.errors
    return journal.transactions[0]


def test_amounts_keep_their_label_and_precision():
    t = _txn(
        "2026-01-05 x\n    Assets:Wise  100.50 INR\n    Equity:O  -100.50 INR\n    Assets:Cash  0.12345678\n    Equity:P  -0.12345678\n"
    )
    assert [(p.amount, p.commodity) for p in t.postings] == [
        (Decimal("100.50"), "INR"),
        (Decimal("-100.50"), "INR"),
        (Decimal("0.12345678"), None),
        (Decimal("-0.12345678"), None),
    ]


def test_a_symbol_before_the_number_is_the_label():
    t = _txn("2026-01-05 x\n    Assets:Wise  ₹8,350\n    Assets:HDFC  -₹8,350\n")
    assert [p.commodity for p in t.postings] == ["₹", "₹"] and t.postings[0].amount == Decimal("8350")


def test_conversions_are_refused_because_finode_keeps_one_currency():
    for price in ("@@ 8350 INR", "@ 83.5 INR"):
        errors = _errors(f"2026-01-05 Buy USD\n    Assets:Wise   100 USD {price}\n    Assets:HDFC   -8350 INR\n")
        assert errors == ["line 2: conversions between currencies are not supported: finode keeps one currency"]


def test_an_amount_without_a_commodity_joins_the_only_one_in_the_transaction():
    assert _errors("2026-01-05 x\n    A:B  10 INR\n    C:D  -10\n") == []
    assert _errors("2026-01-05 x\n    A:B  10\n    C:D  -10 INR\n") == []


def test_a_left_out_amount_takes_the_label_the_others_have():
    t = _txn("2026-01-05 x\n    A:B  10 INR\n    C:D  4 INR\n    E:F\n")
    assert (t.postings[2].amount, t.postings[2].commodity) == (Decimal("-14"), "INR")
    t = _txn("2026-01-05 x\n    A:B  10 USD\n    C:D  5 EUR\n    E:F\n")
    assert (t.postings[2].amount, t.postings[2].commodity) == (Decimal("-15"), None), (
        "different labels: the importer will object"
    )


def test_balance_assertions_are_per_label():
    ok = (
        "2026-01-01 a\n    Assets:Wise  100 INR = 100 INR\n    Equity:O  -100 INR\n"
        "2026-01-02 b\n    Assets:Wise  50 INR = 150 INR\n    Equity:O  -50 INR\n"
    )
    assert _errors(ok) == []
    bad = ok + "2026-01-03 c\n    Assets:Wise  10 INR = 111 INR\n    Equity:O  -10 INR\n"
    assert "balance assertion failed: 'Assets:Wise' is 160.00, expected 111.00" in _errors(bad)[0]


def test_commodity_directives_are_accepted_and_price_lines_are_not():
    assert _errors("commodity 1,000.00 INR\ncommodity INR\n    format 1,000.00 INR\n") == []
    assert _errors("P 2026-01-05 USD 83.5 INR\n") == ["line 1: prices are not supported: finode keeps one currency"]
