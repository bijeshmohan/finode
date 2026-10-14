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

    text = client.get("/transactions").text
    assert text.index("newer-shop") < text.index("older-shop")
    assert "2,000.00" in text
    assert "checking" in text and "groceries" in text


def test_transactions_page_filters(
    client: TestClient, account: dict, other_account: dict, expense_account: dict
):
    _post(client, expense_account, account, "1.00", "2026-01-01", "from-checking")
    _post(client, expense_account, other_account, "1.00", "2026-03-01", "from-savings")

    by_account = client.get("/transactions", params={"account": account["aid"]}).text
    assert "from-checking" in by_account and "from-savings" not in by_account

    by_date = client.get("/transactions", params={"date_from": "2026-02-01"}).text
    assert "from-savings" in by_date and "from-checking" not in by_date


def test_transactions_page_invalid_filter_shows_error(client: TestClient):
    response = client.get("/transactions", params={"date_from": "not-a-date"})
    assert response.status_code == 200
    assert "Invalid filter" in response.text


def test_transactions_page_paginates(client: TestClient, account: dict, expense_account: dict):
    for i in range(27):
        _post(client, expense_account, account, "1.00", "2026-01-01", f"tx-{i:02d}")

    first = client.get("/transactions")
    assert "Older" in first.text and "Newer" not in first.text
    assert first.text.count('class="tx"') == 25

    second = client.get("/transactions", params={"page": 2})
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

    text = client.get("/transactions").text
    assert ">Today<" in text
    assert ">3 Feb 2020<" in text
    assert f'href="/transactions/{tx["tid"]}/edit"' in text


def test_transaction_amounts_are_signed_by_kind(
    client: TestClient, account: dict, other_account: dict, expense_account: dict, income_account: dict
):
    _post(client, expense_account, account, "10.00", "2026-01-01", "shop")
    _post(client, account, income_account, "500.00", "2026-01-02", "pay")
    _post(client, other_account, account, "20.00", "2026-01-03", "move")

    text = client.get("/transactions").text
    assert 'tx-amount expense">−10.00' in text
    assert 'tx-amount income">+500.00' in text
    assert 'tx-amount transfer">20.00' in text


def test_filters_open_with_count_only_when_active(client: TestClient, account: dict):
    closed = client.get("/transactions").text
    assert '<details class="card filters" >' in closed
    opened = client.get(
        "/transactions", params={"account": account["aid"], "date_from": "2026-01-01"}
    ).text
    assert '<details class="card filters" open>' in opened
    assert '<span class="count">2</span>' in opened
    assert "No transactions match these filters." in opened


def test_recurring_is_an_icon_at_the_right_of_the_page_title(client):
    page = client.get("/transactions").text
    head = page[page.index('<div class="page-head">'):page.index("</div>", page.index('<div class="page-head">'))]
    assert head.index("<h1>Transactions</h1>") < head.index('href="/recurring"')
    assert "<svg" in head and 'title="Recurring transactions"' in head
    assert 'class="sr-only">Recurring transactions' in head, "named for screen readers"
    assert '<p class="muted"><a href="/recurring">' not in page, "no visible text link any more"
