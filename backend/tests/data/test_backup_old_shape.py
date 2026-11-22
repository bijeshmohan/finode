"""A backup taken before the four types restores into them: its investments and loans become categories, a group of
the person's own goes, and every account it keeps is one of the types, in the budget (services/cash_flow.py)."""

import json
from uuid import uuid4

from tests.conftest import TEST_USER_ID
from tests.data.test_backup import OTHER, as_user, rich  # noqa: F401  # rich is a fixture


def _old_shape(doc: dict) -> dict:
    """The file as finode wrote it before the four types: Investments with a fund outside the budget, a SIP into it, and
    a group of the person's own holding a wallet."""
    old = json.loads(json.dumps(doc))
    accounts = old["accounts"]
    assets = next(a["id"] for a in accounts if a["name"] == "Assets" and a["parent_id"] is None)
    hdfc = next(a["id"] for a in accounts if a["name"] == "HDFC")
    for a in accounts:
        a["on_budget"] = a.get("type") is not None or a["name"] in ("HDFC", "Visa", "Old Savings")
    group, fund, wallets, paytm = (str(uuid4()) for _ in range(4))
    accounts += [
        {
            "id": group,
            "parent_id": assets,
            "name": "Investments",
            "system_key": "assets.investments",
            "new_accounts_in_budget": False,
        },
        {"id": fund, "parent_id": group, "name": "Axis Bluechip", "on_budget": False},
        {"id": wallets, "parent_id": assets, "name": "Wallets", "new_accounts_in_budget": True},
        {"id": paytm, "parent_id": wallets, "name": "Paytm", "on_budget": True},
    ]
    old["transactions"].append(
        {
            "id": str(uuid4()),
            "date": "2026-09-10",
            "payee": "SIP",
            "postings": [
                {"account": fund, "side": "debit", "amount": "1000"},
                {"account": hdfc, "side": "credit", "amount": "1000"},
            ],
        }
    )
    return old


def test_a_file_from_before_the_four_types_restores_into_them(client, rich):
    old = _old_shape(client.get("/api/backup").json())
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(old), "application/json")})
        assert done.status_code == 200, done.text
        assert client.get("/api/reports/trial-balance").json()["balanced"]
        accounts = client.get("/api/accounts/").json()
        names = {a["name"] for a in accounts}
        assert not names & {"Investments", "Axis Bluechip", "Wallets"}
        paytm = next(a for a in accounts if a["name"] == "Paytm")
        assert paytm["type"] == "assets.bank", "a group of the person's own: its accounts go under a type by root"
        assert all(
            a["type"]
            for a in accounts
            if a["parent_id"] and not a["system_key"] and not a["contact_account"] and a["name"] != "Opening Balances"
        ), "every account kept is one of the four types"
        sip = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "SIP")
        categories = {c["id"]: c["name"] for c in client.get("/api/categories/").json()}
        assert {categories.get(p["category_id"]) for p in sip["postings"]} == {"Axis Bluechip", None}
    finally:
        as_user(TEST_USER_ID)


def test_a_new_file_restores_unchanged(client, rich):
    doc = client.get("/api/backup").json()
    try:
        as_user(OTHER)
        assert (
            client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")}).status_code
            == 200
        )
        again = client.get("/api/backup").json()
        assert sorted(a["name"] for a in again["accounts"]) == sorted(a["name"] for a in doc["accounts"])
        assert len(again["transactions"]) == len(doc["transactions"])
    finally:
        as_user(TEST_USER_ID)


def test_an_old_tracking_account_is_retired_not_put_in_the_budget(client, rich):
    old = _old_shape(client.get("/api/backup").json())
    debts = str(uuid4())
    liabilities = next(a["id"] for a in old["accounts"] if a["name"] == "Liabilities" and a["parent_id"] is None)
    hdfc = next(a["id"] for a in old["accounts"] if a["name"] == "HDFC")
    old["accounts"].append({"id": debts, "parent_id": liabilities, "name": "Car loan", "on_budget": False})
    old["transactions"].append(
        {
            "id": str(uuid4()),
            "date": "2026-09-12",
            "payee": "Car EMI",
            "postings": [
                {"account": debts, "side": "debit", "amount": "900"},
                {"account": hdfc, "side": "credit", "amount": "900"},
            ],
        }
    )
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(old), "application/json")})
        assert done.status_code == 200, done.text
        names = {a["name"] for a in client.get("/api/accounts/").json()}
        assert "Car loan" not in names, "a loan kept outside the budget becomes a category, not a Credit Card"
        categories = {c["name"] for c in client.get("/api/categories/").json()}
        assert "Car loan" in categories
    finally:
        as_user(TEST_USER_ID)
