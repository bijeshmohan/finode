"""A backup taken before the four types restores into them: its investments and loans become categories, the type
accounts and groups go, and every account it keeps sits under its root with a type (services/cash_flow.py). An account
the file gives no type is refused: finode never guesses one."""

import json
from uuid import uuid4

from tests.conftest import TEST_USER_ID
from tests.data.test_backup import OTHER, as_user, rich  # noqa: F401  # rich is a fixture


def _old_shape(doc: dict, wallets_key: str | None = "assets.wallet") -> dict:
    """The file as finode wrote it before: Investments with a fund outside the budget, a SIP into it, and a group
    holding a wallet: the Prepaid Wallet type's own account (`wallets_key`), or, with none, a group of the person's
    own."""
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
        {
            "id": wallets,
            "parent_id": assets,
            "name": "Wallets",
            "new_accounts_in_budget": True,
            "system_key": wallets_key,
        },
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
        roots = {a["id"]: a["name"] for a in accounts if a["parent_id"] is None}
        assert paytm["type"] == "assets.wallet" and roots[paytm["parent_id"]] == "Assets", "straight under its root"
        assert all(
            a["type"] and a["parent_id"] in roots
            for a in accounts
            if a["parent_id"] and not a["contact_account"] and a["name"] != "Opening Balances"
        ), "every account kept is one of the four types, straight under its root"
        sip = next(t for t in client.get("/api/transactions/").json() if t["payee"] == "SIP")
        categories = {c["id"]: c["name"] for c in client.get("/api/categories/").json()}
        assert {categories.get(p["category_id"]) for p in sip["postings"]} == {"Axis Bluechip", None}
    finally:
        as_user(TEST_USER_ID)


def test_an_account_the_file_gives_no_type_is_refused(client, rich):
    old = _old_shape(client.get("/api/backup").json(), wallets_key=None)
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(old), "application/json")})
        assert done.status_code == 400 and "These accounts have no type: Assets:Wallets:Paytm." in done.text
        assert [a for a in client.get("/api/accounts/").json() if a["parent_id"]] == [], "nothing was restored"
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


def _version_6(doc: dict) -> dict:
    """The file as version 6 wrote it: each account under its type's own account (with the type's key), and
    categories two levels deep: Groceries (with lines of its own) holding Dairy, and an unused Travel holding Stay."""
    old = json.loads(json.dumps(doc))
    old["version"] = 6
    roots = {a["name"]: a["id"] for a in old["accounts"] if a["parent_id"] is None}
    nodes: dict[str, str] = {}
    for key, name, root in (
        ("assets.bank", "Bank Account", "Assets"),
        ("assets.cash", "Cash", "Assets"),
        ("liabilities.cards", "Credit Card", "Liabilities"),
        ("assets.wallet", "Prepaid Wallet", "Assets"),
    ):
        nodes[key] = str(uuid4())
        old["accounts"].append({"id": nodes[key], "parent_id": roots[root], "name": name, "system_key": key})
    for a in old["accounts"]:
        kind = a.pop("type", None)
        if kind:
            a["parent_id"] = nodes[kind]
    groceries = next(c for c in old["categories"] if c["name"] == "Groceries")
    travel = str(uuid4())
    old["categories"] += [
        {"id": str(uuid4()), "name": "Dairy", "kind": "spending", "parent_id": groceries["id"]},
        {"id": travel, "name": "Travel", "kind": "spending"},
        {"id": str(uuid4()), "name": "Stay", "kind": "spending", "parent_id": travel},
    ]
    return old


def test_a_version_6_file_restores_flat(client, rich):
    doc = client.get("/api/backup").json()
    assert doc["version"] == 7
    types = {a["name"]: a["type"] for a in doc["accounts"] if a.get("type")}
    closed = {a["name"] for a in doc["accounts"] if a["closed_on"]}
    ready = client.get("/api/budget/").json()["ready_to_assign"]
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(_version_6(doc)), "application/json")})
        assert done.status_code == 200, done.text
        accounts = client.get("/api/accounts/").json()
        roots = {a["id"] for a in accounts if a["parent_id"] is None}
        assert all(a["parent_id"] in roots for a in accounts if a["parent_id"]), "straight under the roots"
        assert {a["name"]: a["type"] for a in accounts if a["type"]} == types
        assert {a["name"] for a in accounts if a["closed_on"]} == closed, "a closed account stays closed"
        assert not {a["name"] for a in accounts} & {"Bank Account", "Cash", "Credit Card", "Prepaid Wallet"}
        names = {c["name"] for c in client.get("/api/categories/", params={"include_closed": True}).json()}
        assert {"Groceries", "Dairy", "Stay"} <= names and "Travel" not in names
        assert client.get("/api/budget/").json()["ready_to_assign"] == ready
        assert client.get("/api/reports/trial-balance").json()["balanced"]
    finally:
        as_user(TEST_USER_ID)


def test_a_version_7_file_with_an_untyped_account_is_refused(client, rich):
    doc = client.get("/api/backup").json()
    assets = next(a["id"] for a in doc["accounts"] if a["name"] == "Assets" and a["parent_id"] is None)
    doc["accounts"].append({"id": str(uuid4()), "parent_id": assets, "name": "Loose"})
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 400 and "These accounts have no type: Assets:Loose." in done.text
        assert [a for a in client.get("/api/accounts/").json() if a["parent_id"]] == [], "nothing was restored"
    finally:
        as_user(TEST_USER_ID)
