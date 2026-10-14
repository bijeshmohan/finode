from datetime import date

from fastapi.testclient import TestClient


def test_dashboard_empty_state(client: TestClient):
    response = client.get("/")
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
        "/api/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"},
    ).json()
    today = date.today().isoformat()
    for debit, credit, amount, payee in (
        (bank, income_account, "2500.00", "Employer"),
        (expense_account, bank, "120.50", "Supermarket"),
    ):
        response = client.post(
            "/api/transactions/",
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

    text = client.get("/").text
    assert "3,379.50" in text  # net worth: 1000 + 2500 - 120.50
    assert "2,500.00" in text  # income this month
    assert "120.50" in text  # expenses this month
    assert "Employer" in text and "Supermarket" in text


def test_dashboard_limits_recent_transactions(
    client: TestClient, account: dict, expense_account: dict
):
    for i in range(10):
        client.post(
            "/api/transactions/",
            json={
                "payee": f"tx-{i}",
                "postings": [
                    {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                    {"account": account["aid"], "side": "credit", "amount": "1.00"},
                ],
            },
        )
    text = client.get("/").text
    assert text.count('class="tx"') == 8


def test_friendly_date_filter():
    from datetime import timedelta

    from app.templating import friendly_date

    today = date.today()
    assert friendly_date(today) == "Today"
    assert friendly_date(today - timedelta(days=1)) == "Yesterday"
    assert friendly_date(date(2020, 2, 3)) == "3 Feb 2020"
    assert friendly_date(date(today.year, 1, 1) if today.month > 1 or today.day > 2 else today) in (
        f"{date(today.year, 1, 1):%a}, 1 Jan",
        "Today",
    )


def test_onboarding_checklist_for_new_users(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/").text
    assert "Get started" in text
    assert f'href="/accounts/new?parent={root_accounts["Assets"]}"' in text
    assert f'href="/accounts/new?parent={root_accounts["Expenses"]}"' in text
    assert 'href="/transactions/new">Record your first transaction' in text


def test_onboarding_ticks_off_steps_and_ignores_opening_balances(
    client: TestClient, root_accounts: dict[str, str]
):
    bank = client.post(
        "/api/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"},
    ).json()
    text = client.get("/").text
    assert '<li class="done">' in text
    assert "Record your first transaction</a>" in text  # opening balance is not a recorded transaction

    food = client.post(
        "/api/accounts/", json={"name": "food", "parent_id": root_accounts["Expenses"]}
    ).json()
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": food["aid"], "side": "debit", "amount": "5.00"},
                {"account": bank["aid"], "side": "credit", "amount": "5.00"},
            ]
        },
    )
    assert "Get started" not in client.get("/").text


def test_money_filter_groups_digits_and_uses_a_true_minus():
    from decimal import Decimal

    from app.templating import money

    assert money(Decimal("1234567.5")) == "1,234,567.50"
    assert money("-2652.75") == "−2,652.75"
    assert money(None) == ""
