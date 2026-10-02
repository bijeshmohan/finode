from datetime import date

from fastapi.testclient import TestClient


def test_dashboard_empty_state(client: TestClient):
    response = client.get("/app/")
    assert response.status_code == 200
    assert "Net worth" in response.text
    assert "Nothing recorded yet" in response.text
    assert date.today().strftime("%B %Y") in response.text


def test_dashboard_shows_summary_and_recent_transactions(
    client: TestClient,
    root_accounts: dict[str, str],
    income_account: dict,
    expense_account: dict,
):
    bank = client.post(
        "/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"},
    ).json()
    today = date.today().isoformat()
    for debit, credit, amount, payee in (
        (bank, income_account, "2500.00", "Employer"),
        (expense_account, bank, "120.50", "Supermarket"),
    ):
        response = client.post(
            "/transactions/",
            json={
                "date": today,
                "payee": payee,
                "postings": [
                    {"account": debit["aid"], "side": "debit", "amount": amount},
                    {"account": credit["aid"], "side": "credit", "amount": amount},
                ],
            },
        )
        assert response.status_code == 201

    text = client.get("/app/").text
    assert "3,379.50" in text  # net worth: 1000 + 2500 - 120.50
    assert "2,500.00" in text  # income this month
    assert "120.50" in text  # expenses this month
    assert "Employer" in text and "Supermarket" in text


def test_dashboard_limits_recent_transactions(
    client: TestClient, account: dict, expense_account: dict
):
    for i in range(10):
        client.post(
            "/transactions/",
            json={
                "payee": f"tx-{i}",
                "postings": [
                    {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                    {"account": account["aid"], "side": "credit", "amount": "1.00"},
                ],
            },
        )
    text = client.get("/app/").text
    assert text.count("<tr>") == 1 + 8  # header row + 8 recent
