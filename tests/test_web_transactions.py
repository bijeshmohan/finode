import re
from datetime import date

from fastapi.testclient import TestClient


def _post(client: TestClient, debit: dict, credit: dict, amount: str, on: str, payee: str):
    response = client.post(
        "/api/transactions/",
        json={
            "date": on,
            "payee": payee,
            "postings": [
                {"account": debit["aid"], "side": "debit", "amount": amount},
                {"account": credit["aid"], "side": "credit", "amount": amount},
            ],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_transactions_page_empty(client: TestClient):
    response = client.get("/transactions")
    assert response.status_code == 200
    assert "No transactions yet." in response.text
    assert 'href="/transactions/new"' in response.text


def test_transactions_page_lists_newest_first(
    client: TestClient, account: dict, expense_account: dict
):
    _post(client, expense_account, account, "10.00", "2026-01-01", "older-shop")
    _post(client, expense_account, account, "2000.00", "2026-02-01", "newer-shop")

    text = client.get("/transactions", params={"date_from": "2026-01-01"}).text
    assert text.index("newer-shop") < text.index("older-shop")
    assert "2,000.00" in text
    assert "checking" in text and "groceries" in text


def listed(html: str) -> str:
    """The page without the Filter sheet, whose lists name every account and payee."""
    return re.sub(r'<dialog class="sheet sheet-bottom" id="tx-filter".*?</dialog>', "", html, flags=re.S)


def test_transactions_page_filters(
    client: TestClient, account: dict, other_account: dict, expense_account: dict
):
    _post(client, expense_account, account, "1.00", "2026-01-01", "from-checking")
    _post(client, expense_account, other_account, "1.00", "2026-03-01", "from-savings")

    by_account = client.get("/transactions", params={"account": account["aid"], "date_from": "2026-01-01"}).text
    by_account = listed(by_account)
    assert "from-checking" in by_account and "from-savings" not in by_account

    by_date = listed(client.get("/transactions", params={"date_from": "2026-02-01"}).text)
    assert "from-savings" in by_date and "from-checking" not in by_date


def test_transactions_page_invalid_filter_shows_error(client: TestClient):
    response = client.get("/transactions", params={"date_from": "not-a-date"})
    assert response.status_code == 200
    assert "Invalid filter" in response.text


def test_transactions_page_paginates(client: TestClient, account: dict, expense_account: dict):
    for i in range(27):
        _post(client, expense_account, account, "1.00", "2026-01-01", f"tx-{i:02d}")

    first = client.get("/transactions", params={"date_from": "2026-01-01"})
    assert "Older" in first.text and "Newer" not in first.text
    assert first.text.count('class="tx"') == 25

    second = client.get("/transactions", params={"page": 2, "date_from": "2026-01-01"})
    assert second.text.count('class="tx"') == 2
    assert "Newer" in second.text and "Older" not in second.text


def test_delete_transaction_from_ui(client: TestClient, account: dict, expense_account: dict):
    tx = _post(client, expense_account, account, "5.00", "2026-01-01", "oops")
    response = client.post(f"/transactions/{tx['tid']}/delete")
    assert response.status_code == 200
    assert response.headers["HX-Redirect"] == "/transactions"
    assert client.get("/api/transactions/").json() == []


def test_delete_missing_transaction_shows_error(client: TestClient):
    response = client.post("/transactions/00000000-0000-4000-8000-0000000000ff/delete")
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#page-error"


def test_transactions_are_grouped_by_friendly_day_and_link_to_edit(
    client: TestClient, account: dict, expense_account: dict
):
    today = date.today()
    tx = _post(client, expense_account, account, "5.00", today.isoformat(), "coffee")
    _post(client, expense_account, account, "7.00", "2020-02-03", "old")

    text = client.get("/transactions", params={"date_from": "2020-01-01"}).text
    assert ">Today<" in text
    assert ">3 Feb 2020<" in text
    assert f'href="/transactions/{tx["tid"]}/edit"' in text


def test_a_day_with_several_entries_shows_what_was_spent_that_day(client: TestClient, account: dict, expense_account: dict):
    _post(client, expense_account, account, "5.00", "2020-02-03", "coffee")
    _post(client, expense_account, account, "7.50", "2020-02-03", "snack")
    _post(client, expense_account, account, "2.00", "2020-02-04", "tea")

    text = client.get("/transactions", params={"date_from": "2020-01-01"}).text
    assert '<span class="tx-day-total">Spent 12.50</span>' in text
    assert '<span class="tx-day-total">Spent 2.00</span>' not in text, "one entry would only repeat its row"


def test_transaction_amounts_use_colour_not_a_minus_sign(
    client: TestClient, account: dict, other_account: dict, expense_account: dict, income_account: dict
):
    _post(client, expense_account, account, "10.00", "2026-01-01", "shop")
    _post(client, account, income_account, "500.00", "2026-01-02", "pay")
    _post(client, other_account, account, "20.00", "2026-01-03", "move")

    text = client.get("/transactions", params={"date_from": "2026-01-01"}).text
    assert 'tx-amount expense">10.00' in text, "an ordinary expense has no sign (it is the default)"
    assert "−" not in text.split("tx-list")[1].split("txn-sheet")[0]
    assert 'tx-amount income">+500.00' in text
    assert 'tx-amount transfer">20.00' in text


def test_the_filter_word_counts_what_is_set(client: TestClient, account: dict):
    closed = client.get("/transactions").text
    assert "data-open-filter" in closed and "All transactions" in closed and 'class="tx-applied"' not in closed
    opened = client.get("/transactions", params={"account": account["aid"], "date_from": "2026-01-01"}).text
    assert "Filter · 1" in opened and 'class="tx-applied"' in opened
    assert "Nothing matches." in listed(opened)


def test_nothing_sits_beside_the_kind_chips_recurring_and_deleted_are_in_settings(client):
    page = client.get("/transactions").text
    head = page[page.index('<div class="tx-filterbar">'):page.index("</dialog>")]
    assert "head-icons" not in head and 'href="/recurring"' not in page and 'href="/transactions/deleted"' not in page
    settings = client.get("/settings").text
    assert 'href="/recurring"' in settings and 'href="/accounts/deleted"' in settings


def test_the_month_pill_lists_one_month_and_has_no_search_box(client: TestClient, account: dict, expense_account: dict):
    today = date.today()
    _post(client, expense_account, account, "10", today.isoformat(), "ThisMonth")
    _post(client, expense_account, account, "20", "2026-01-15", "InJanuary")
    now = listed(client.get("/transactions").text)
    assert "ThisMonth" in now and "InJanuary" not in now
    assert 'class="month-input"' in now and 'type="search"' not in now
    january = listed(client.get("/transactions", params={"month": "2026-01"}).text)
    assert "InJanuary" in january and "ThisMonth" not in january
    assert "Jan 2026" in january
    ahead = listed(client.get("/transactions", params={"month": "2999-01"}).text)
    assert "ThisMonth" in ahead, "a month that has not started opens this month"
