"""The full backup: everything is in the file, and restoring it rebuilds the same books for another user."""

import json
from uuid import UUID

import pytest

from app.auth import CurrentUser, require_authenticated_user
from app.main import app

from .conftest import TEST_USER_ID

OTHER = UUID("00000000-0000-4000-8000-0000000000bb")


def acct(client, name, parent, **extra):
    response = client.post("/api/accounts/", json={"name": name, "parent_id": parent, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def tx(client, postings, **extra):
    response = client.post("/api/transactions/", json={"postings": postings, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def line(account, side, amount, **extra):
    return {"account": account["aid"], "side": side, "amount": amount, **extra}


@pytest.fixture
def rich(client, root_accounts):
    """A ledger that uses every feature a backup has to carry."""
    client.patch("/api/profile/", json={"first_name": "Ada", "last_name": "L", "default_currency": "INR"})
    banks = acct(client, "Banks", root_accounts["Assets"])
    bank = acct(client, "HDFC", banks["aid"], balance="50000", details="main account")
    old = acct(client, "Old Savings", banks["aid"])
    crypto = acct(client, "Coins", root_accounts["Assets"], commodity="BTC")
    card = acct(client, "Visa", root_accounts["Liabilities"], on_budget=True)
    loan = acct(client, "Home Loan", root_accounts["Liabilities"], on_budget=False)
    food = acct(client, "Food", root_accounts["Expenses"])
    groceries = acct(client, "Groceries", food["aid"])
    emi = acct(client, "EMI", root_accounts["Expenses"])
    salary = acct(client, "Salary", root_accounts["Income"])
    client.patch(f"/api/accounts/{loan['aid']}", json={"payment_category_id": emi["aid"]})
    assert client.post(f"/api/accounts/{old['aid']}/close").status_code == 200

    tx(client, [line(groceries, "debit", "250"), line(card, "credit", "250")], date="2026-09-03", payee="DMart")
    tx(client, [line(bank, "debit", "90000"), line(salary, "credit", "90000")], date="2026-09-01", payee="Employer")
    tx(client, [line(loan, "debit", "15000"), line(bank, "credit", "15000")], date="2026-09-05", payee="EMI")
    tx(client, [line(groceries, "debit", "100"), line(food, "debit", "50"), line(bank, "credit", "150")],
       date="2026-09-06", comment="split")
    tx(client, [line(crypto, "debit", "0.01", value="5000"), line(bank, "credit", "5000")], date="2026-09-07", payee="Exchange")
    assert client.post("/api/prices/", json={"commodity": "BTC", "quote": "INR", "date": "2026-09-08", "price": "510000.5"}).status_code == 201

    client.post("/api/recurring/", json={
        "from_account": bank["aid"], "to_account": groceries["aid"], "amount": "500", "frequency": "monthly",
        "start_date": "2026-07-01", "payee": "Milk",
    })
    client.post("/api/recurring/", json={
        "postings": [line(groceries, "debit", "60"), line(food, "debit", "40"), line(bank, "credit", "100")],
        "frequency": "weekly", "start_date": "2999-01-01", "payee": "Split rule",
    })
    client.put(f"/api/budget/categories/{groceries['aid']}", json={"month": "2026-09-01", "amount": "3000"})
    client.put(f"/api/budget/categories/{emi['aid']}", json={"month": "2026-09-01", "amount": "15000"})
    client.put(f"/api/budget/categories/{groceries['aid']}/target", json={"kind": "monthly", "amount": "3000"})
    return {"bank": bank, "groceries": groceries}


def as_user(user_id):
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(id=user_id, email="x@example.com", claims={})


def canonical(doc: dict) -> dict:
    """A backup without ids and timestamps: accounts by path, everything pointing at them by path."""
    by_id = {a["id"]: a for a in doc["accounts"]}

    def path(aid):
        names = []
        while aid:
            names.append(by_id[aid]["name"])
            aid = by_id[aid]["parent_id"]
        return ":".join(reversed(names))

    paths = {aid: path(aid) for aid in by_id}
    rules = {r["id"]: (r["payee"], r["frequency"]) for r in doc["recurring"]}
    return {
        "profile": doc["profile"],
        "commodities": sorted(doc["commodities"], key=lambda c: c["code"]),
        "prices": doc["prices"],
        "accounts": sorted(
            (paths[a["id"]], a["details"], a["commodity"], a["on_budget"], a["closed_on"] is not None,
             paths.get(a["payment_category_id"]))
            for a in doc["accounts"]
        ),
        "transactions": [
            (t["date"], t["payee"], t["comment"], t["currency"], t["created_via"], rules.get(t["recurring_id"]), t["recurring_date"],
             sorted((paths[p["account"]], p["side"], p["amount"], p["value"]) for p in t["postings"]))
            for t in doc["transactions"]
        ],
        "recurring": sorted(
            (r["payee"], paths.get(r["from_account"]), paths.get(r["to_account"]), r["amount"], r["currency"],
             sorted((paths[p["account"]], p["side"], p["amount"], p["value"]) for p in r["postings"]),
             r["frequency"], r["start_date"], r["next_date"], r["last_date"], r["active"])
            for r in doc["recurring"]
        ),
        "allocations": sorted((a["month"], paths[a["account_id"]], a["amount"]) for a in doc["allocations"]),
        "targets": sorted((paths[t["account_id"]], t["kind"], t["amount"]) for t in doc["targets"]),
    }


def test_the_backup_has_everything(client, rich):
    response = client.get("/api/backup")
    assert response.status_code == 200 and 'attachment; filename="finode-backup-' in response.headers["content-disposition"]
    doc = response.json()
    assert doc["format"] == "finode-backup" and doc["version"] == 1
    assert doc["profile"]["first_name"] == "Ada" and doc["profile"]["default_currency"] == "INR"
    assert [c["code"] for c in doc["commodities"]] == ["BTC"]
    names = {a["name"] for a in doc["accounts"]}
    assert {"Banks", "HDFC", "Old Savings", "Coins", "Visa", "Home Loan", "Groceries", "EMI", "Opening Balances", "Assets"} <= names
    assert any(a["closed_on"] for a in doc["accounts"]) and any(a["payment_category_id"] for a in doc["accounts"])
    assert any(a["on_budget"] for a in doc["accounts"])
    assert len(doc["recurring"]) == 2 and any(r["postings"] for r in doc["recurring"])
    assert any(t["recurring_id"] for t in doc["transactions"]), "recorded occurrences keep their rule"
    assert len(doc["allocations"]) == 2 and len(doc["targets"]) == 1
    assert len(doc["prices"]) == 1 and doc["prices"][0]["commodity"] == "BTC" and doc["prices"][0]["quote"] == "INR"
    assert set(doc) == {"format", "version", "exported_at", "profile", "commodities", "prices", "accounts", "transactions", "recurring", "allocations", "targets"}, "no tokens or connected apps"


def test_restoring_rebuilds_the_same_books_for_someone_else(client, rich):
    doc = client.get("/api/backup").json()
    try:
        as_user(OTHER)
        assert client.get("/api/backup").json()["transactions"] == []
        preview = client.post("/api/restore", params={"dry_run": True}, files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert preview.status_code == 200 and preview.json()["transactions"] == len(doc["transactions"])
        assert client.get("/api/backup").json()["transactions"] == [], "a preview saves nothing"
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 200, done.text
        again = client.get("/api/backup").json()
        assert client.get("/api/reports/trial-balance").json()["balanced"]
    finally:
        as_user(TEST_USER_ID)
    assert canonical(again) == canonical(doc)
    # The new books work like the old ones: balances agree, ids are new.
    old_ids = {a["id"] for a in doc["accounts"] if a["parent_id"]}
    assert not old_ids & {a["id"] for a in again["accounts"] if a["parent_id"]}


def test_a_restore_is_only_for_an_empty_ledger(client, rich):
    doc = client.get("/api/backup").json()
    refused = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
    assert refused.status_code == 400 and "empty ledger" in str(refused.json()["detail"])


def test_a_broken_file_is_refused_and_saves_nothing(client, rich):
    doc = client.get("/api/backup").json()
    try:
        as_user(OTHER)

        def post(body):
            return client.post("/api/restore", files={"file": ("b.json", body if isinstance(body, str) else json.dumps(body), "application/json")})

        assert post("not json").status_code == 400
        assert post({"format": "other", "version": 1, "profile": {"default_currency": "INR"}, "accounts": []}).status_code == 400
        wrong_version = {**doc, "version": 99}
        assert "version 99" in str(post(wrong_version).json())
        unbalanced = json.loads(json.dumps(doc))
        unbalanced["transactions"][0]["postings"][0]["value"] = "1"
        refused = post(unbalanced)
        assert refused.status_code == 400 and "does not balance" in str(refused.json())
        missing = json.loads(json.dumps(doc))
        missing["transactions"][0]["postings"][0]["account"] = "00000000-0000-4000-8000-0000000000ff"
        assert "not in the file" in str(post(missing).json())
        cycle = json.loads(json.dumps(doc))
        banks = next(a for a in cycle["accounts"] if a["name"] == "Banks")
        hdfc = next(a for a in cycle["accounts"] if a["name"] == "HDFC")
        banks["parent_id"] = hdfc["id"]
        assert post(cycle).status_code == 400
        assert client.get("/api/backup").json()["transactions"] == [] and not [
            a for a in client.get("/api/backup").json()["accounts"] if a["parent_id"]
        ], "nothing was saved"
    finally:
        as_user(TEST_USER_ID)


def test_the_data_page_offers_backup_and_restore(client, rich):
    page = client.get("/profile/data").text
    assert 'href="/backup"' in page and "Full backup" in page
    assert "only be restored into an empty ledger" in page
    assert client.get("/backup").headers["content-type"].startswith("application/json")


def test_the_restore_pages(client, rich):
    doc = client.get("/api/backup").json()
    files = {"file": ("b.json", json.dumps(doc), "application/json")}
    try:
        as_user(OTHER)
        assert "Preview restore" in client.get("/profile/data").text
        preview = client.post("/restore/preview", files=files)
        assert "Ready to restore" in preview.text and f"{len(doc['transactions'])} transactions" in preview.text
        assert "Restore everything" in preview.text
        bad = client.post("/restore/preview", files={"file": ("b.json", "nope", "application/json")})
        assert "Nothing was restored" in bad.text
        done = client.post("/restore", files=files)
        assert done.headers["HX-Redirect"] == "/" and "restore-done" in done.headers["set-cookie"]
        again = client.post("/restore", files=files)
        assert "Nothing was restored" in again.text and "empty ledger" in again.text
    finally:
        as_user(TEST_USER_ID)
