"""Entries dated ahead are not history: out of Home's recent list, and in their own row on the transactions page."""

from datetime import date, timedelta

import pytest

from app.clock import local_today


@pytest.fixture
def ledger(client, root_accounts):
    def make(name, parent, **extra):
        return client.post("/api/accounts/", json={"name": name, "parent_id": parent, **extra}).json()["aid"]

    bank = make("Bank", root_accounts["Assets"], balance="5000")
    loan = make("Bicycle loan", root_accounts["Liabilities"])
    return bank, loan


def record(client, bank, loan, payee, on):
    r = client.post("/api/transactions/", json={"date": on.isoformat(), "payee": payee, "postings": [
        {"account": loan, "side": "debit", "amount": "100"},
        {"account": bank, "side": "credit", "amount": "100"},
    ]})
    assert r.status_code == 201, r.text


def test_home_leaves_out_what_is_dated_ahead(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "Paid already", local_today())
    record(client, bank, loan, "EMI next month", local_today() + timedelta(days=40))
    page = client.get("/").text
    assert "Paid already" in page and "EMI next month" not in page


def test_the_transactions_page_keeps_them_in_one_collapsed_row(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "Paid already", local_today())
    for i, days in enumerate((40, 10, 70)):
        record(client, bank, loan, f"EMI {i}", local_today() + timedelta(days=days))
    page = client.get("/transactions").text
    assert "3 upcoming" in page and '<details class="upcoming"' in page and 'class="upcoming" open' not in page
    ahead, history = page.split('<details class="upcoming"', 1)[1].split("</details>", 1)
    assert ahead.index("EMI 1") < ahead.index("EMI 0") < ahead.index("EMI 2"), "soonest first"
    assert "Paid already" in history and "EMI" not in history, "the main list is history only"
    assert page.count('id="txn-sheet"') == 1


def test_only_upcoming_entries_still_gets_a_sheet_and_no_empty_state(client, ledger):
    bank, loan = ledger
    # the opening balance is an entry too: the search leaves only the one dated ahead
    record(client, bank, loan, "EMI later", local_today() + timedelta(days=20))
    page = client.get("/transactions?q=EMI later").text
    assert "1 upcoming" in page and "Nothing matches" not in page and page.count('id="txn-sheet"') == 1
    assert 'class="upcoming" open' in page, "a search opens the row so the match is visible"


def test_a_date_range_in_the_future_lists_what_falls_in_it(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "EMI soon", local_today() + timedelta(days=5))
    record(client, bank, loan, "EMI far", local_today() + timedelta(days=90))
    start, end = local_today() + timedelta(days=1), local_today() + timedelta(days=30)
    page = client.get(f"/transactions?date_from={start}&date_to={end}").text
    assert "EMI soon" in page and "EMI far" not in page and "1 upcoming" in page


def test_later_pages_have_no_upcoming_row(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "EMI later", local_today() + timedelta(days=20))
    assert '<details class="upcoming"' in client.get("/transactions").text
    assert '<details class="upcoming"' not in client.get("/transactions?page=2").text
