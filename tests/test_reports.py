from datetime import date

import pytest
from fastapi.testclient import TestClient

from .books import post_account
from .svc import plain


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


def test_summary_empty(client: TestClient, svc):
    data = plain(svc.reports.summary())
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
    svc,
):
    bank = post_account(client, {"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}).json()
    card = post_account(client, {"name": "card", "parent_id": root_accounts["Liabilities"], "balance": "200.00"}).json()
    _transfer(client, bank, income_account, "500.00", "2026-03-10")
    _transfer(client, expense_account, bank, "120.00", "2026-03-12")
    _transfer(client, expense_account, card, "30.00", "2026-04-01")

    march = plain(svc.reports.summary(date(2026, 3, 1), date(2026, 3, 31)))
    assert march["income"] == "500.00"
    assert march["expenses"] == "120.00"
    assert march["net_income"] == "380.00"
    # assets: 1000 + 500 - 120, liabilities: 200 + 30
    assert march["assets"] == "1380.00"
    assert march["liabilities"] == "230.00"
    assert march["net_worth"] == "1150.00"

    april = plain(svc.reports.summary(date(2026, 4, 1), date(2026, 4, 30)))
    assert april["income"] == "0.00"
    assert april["expenses"] == "30.00"


def test_summary_rejects_inverted_period(svc):
    with pytest.raises(ValueError, match="period start must not be after period end!"):
        svc.reports.summary(date(2026, 5, 1), date(2026, 4, 1))
