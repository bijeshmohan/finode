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
    assert "prices" in _errors("2026-10-04 x\n    Assets:A  10 AAPL @ 5 USD\n    Assets:B\n")[0]
    assert "automated" in _errors("= expenses\n    (Assets:A)  1\n")[0]
    assert "unsupported directive 'include'" in _errors("include other.ledger\n")[0]
    assert "balance assignments" in _errors("2026-10-04 x\n    Assets:A  = 5\n    Assets:B\n")[0]
    assert "decimal mark" in _errors("decimal-mark ,\n")[0]


def test_too_many_decimals_and_bad_numbers():
    assert "more than 2 decimal places" in _errors("2026-10-04 x\n    A:B  1.234\n    C:D  -1.234\n")[0]
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
