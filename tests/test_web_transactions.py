from datetime import date

from fastapi.testclient import TestClient


def _post(client: TestClient, debit: dict, credit: dict, amount: str, on: str, payee: str):
    response = client.post(
        "/transactions/",
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
    response = client.get("/app/transactions")
    assert response.status_code == 200
    assert "No transactions found." in response.text


def test_transactions_page_lists_newest_first(
    client: TestClient, account: dict, expense_account: dict
):
    _post(client, expense_account, account, "10.00", "2026-01-01", "older-shop")
    _post(client, expense_account, account, "2000.00", "2026-02-01", "newer-shop")

    text = client.get("/app/transactions").text
    assert text.index("newer-shop") < text.index("older-shop")
    assert "2,000.00" in text
    assert "checking" in text and "groceries" in text


def test_transactions_page_filters(
    client: TestClient, account: dict, other_account: dict, expense_account: dict
):
    _post(client, expense_account, account, "1.00", "2026-01-01", "from-checking")
    _post(client, expense_account, other_account, "1.00", "2026-03-01", "from-savings")

    by_account = client.get("/app/transactions", params={"account": account["aid"]}).text
    assert "from-checking" in by_account and "from-savings" not in by_account

    by_date = client.get("/app/transactions", params={"date_from": "2026-02-01"}).text
    assert "from-savings" in by_date and "from-checking" not in by_date


def test_transactions_page_invalid_filter_shows_error(client: TestClient):
    response = client.get("/app/transactions", params={"date_from": "not-a-date"})
    assert response.status_code == 200
    assert "Invalid filter" in response.text


def test_transactions_page_paginates(client: TestClient, account: dict, expense_account: dict):
    for i in range(27):
        _post(client, expense_account, account, "1.00", "2026-01-01", f"tx-{i:02d}")

    first = client.get("/app/transactions")
    assert "Older" in first.text and "Newer" not in first.text
    assert first.text.count("hx-post=\"/app/transactions/") == 25

    second = client.get("/app/transactions", params={"page": 2})
    assert second.text.count("hx-post=\"/app/transactions/") == 2
    assert "Newer" in second.text and "Older" not in second.text


def test_delete_transaction_from_ui(client: TestClient, account: dict, expense_account: dict):
    tx = _post(client, expense_account, account, "5.00", "2026-01-01", "oops")
    response = client.post(f"/app/transactions/{tx['tid']}/delete")
    assert response.status_code == 200
    assert response.headers["HX-Refresh"] == "true"
    assert client.get("/transactions/").json() == []


def test_delete_missing_transaction_shows_error(client: TestClient):
    response = client.post("/app/transactions/00000000-0000-4000-8000-0000000000ff/delete")
    assert response.status_code == 400
    assert response.headers["HX-Retarget"] == "#page-error"
