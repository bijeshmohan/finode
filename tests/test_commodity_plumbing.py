"""Every account, transaction and posting carries its commodity, currency and value."""

from decimal import Decimal


def _txn(client, debit, credit, amount="25.00"):
    response = client.post(
        "/api/transactions/",
        json={
            "date": "2026-01-05",
            "postings": [
                {"account": debit, "side": "debit", "amount": amount},
                {"account": credit, "side": "credit", "amount": amount},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_root_accounts_are_totalled_in_the_default_currency_and_new_accounts_hold_it(client, root_accounts, account):
    accounts = {a["name"]: a for a in client.get("/api/accounts/").json()}
    assert all(accounts[name]["commodity"] == "INR" for name in root_accounts)
    assert account["commodity"] == "INR"


def test_sub_accounts_inherit_their_parents_commodity(client, account):
    child = client.post("/api/accounts/", json={"name": "wallet", "parent_id": account["aid"]}).json()
    assert child["commodity"] == "INR"


def test_the_opening_balance_account_holds_the_default_currency(client, account):
    client.patch(f"/api/accounts/{account['aid']}", json={"balance": "150.00"})
    opening = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Opening Balances")
    assert opening["commodity"] == "INR"


def test_transactions_are_in_the_default_currency_and_postings_carry_their_value(
    client, account, expense_account
):
    txn = _txn(client, expense_account["aid"], account["aid"], "25.50")
    assert txn["currency"] == "INR"
    assert [(p["amount"], p["value"]) for p in txn["postings"]] == [("25.50", "25.50")] * 2
    fetched = client.get(f"/api/transactions/{txn['tid']}").json()
    assert fetched["currency"] == "INR"
    assert all(Decimal(p["value"]) == Decimal(p["amount"]) for p in fetched["postings"])


def test_opening_balance_postings_carry_a_value(client, account):
    client.patch(f"/api/accounts/{account['aid']}", json={"balance": "150.00"})
    txn = client.get("/api/transactions/").json()[0]
    assert txn["currency"] == "INR"
    assert all(p["value"] == p["amount"] == "150.00" for p in txn["postings"])


def test_editing_postings_keeps_value_in_step(client, account, expense_account):
    txn = _txn(client, expense_account["aid"], account["aid"], "10.00")
    response = client.patch(
        f"/api/transactions/{txn['tid']}",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "40.00"},
                {"account": account["aid"], "side": "credit", "amount": "40.00"},
            ]
        },
    )
    assert response.status_code == 200
    assert all(p["value"] == p["amount"] == "40.00" for p in response.json()["postings"])
    assert response.json()["currency"] == "INR"


def test_balances_still_read_with_two_decimals(client, account, expense_account):
    _txn(client, expense_account["aid"], account["aid"], "25")
    balances = {a["name"]: a["balance"] for a in client.get("/api/accounts/").json()}
    assert balances["groceries"] == "25.00"
    assert balances["checking"] == "-25.00"


def test_the_profile_reports_the_default_currency(client):
    assert client.get("/api/profile/").json()["default_currency"] == "INR"
    client.patch("/api/profile/", json={"first_name": "Asha"})
    assert client.get("/api/profile/").json()["default_currency"] == "INR"
