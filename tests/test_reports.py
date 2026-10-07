from datetime import date

from fastapi.testclient import TestClient


def _transfer(client: TestClient, debit: dict, credit: dict, amount: str, on: str):
    response = client.post(
        "/api/transactions/",
        json={
            "date": on,
            "postings": [
                {"account": debit["aid"], "side": "debit", "amount": amount},
                {"account": credit["aid"], "side": "credit", "amount": amount},
            ],
        },
    )
    assert response.status_code == 201


def test_summary_empty(client: TestClient):
    response = client.get("/api/reports/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["net_worth"] == "0.00"
    assert data["income"] == "0.00"
    assert data["expenses"] == "0.00"
    assert data["period_end"] == date.today().isoformat()
    assert data["period_start"] == date.today().replace(day=1).isoformat()


def test_summary_net_worth_and_period_totals(
    client: TestClient,
    root_accounts: dict[str, str],
    income_account: dict,
    expense_account: dict,
):
    bank = client.post(
        "/api/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"},
    ).json()
    card = client.post(
        "/api/accounts/",
        json={"name": "card", "parent_id": root_accounts["Liabilities"], "balance": "200.00"},
    ).json()
    _transfer(client, bank, income_account, "500.00", "2026-03-10")
    _transfer(client, expense_account, bank, "120.00", "2026-03-12")
    _transfer(client, expense_account, card, "30.00", "2026-04-01")

    march = client.get(
        "/api/reports/summary", params={"date_from": "2026-03-01", "date_to": "2026-03-31"}
    ).json()
    assert march["income"] == "500.00"
    assert march["expenses"] == "120.00"
    assert march["net_income"] == "380.00"
    # assets: 1000 + 500 - 120, liabilities: 200 + 30
    assert march["assets"] == "1380.00"
    assert march["liabilities"] == "230.00"
    assert march["net_worth"] == "1150.00"

    april = client.get(
        "/api/reports/summary", params={"date_from": "2026-04-01", "date_to": "2026-04-30"}
    ).json()
    assert april["income"] == "0.00"
    assert april["expenses"] == "30.00"


def test_summary_rejects_inverted_period(client: TestClient):
    response = client.get(
        "/api/reports/summary", params={"date_from": "2026-05-01", "date_to": "2026-04-01"}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "period start must not be after period end!"
