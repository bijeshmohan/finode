"""The full backup: everything is in the file, and restoring it rebuilds the same books for another user."""

import json
from uuid import UUID

import pytest

from app.auth import CurrentUser, require_authenticated_user
from app.main import app

from .books import into, leg, post_account
from .conftest import TEST_USER_ID

OTHER = UUID("00000000-0000-4000-8000-0000000000bb")


def acct(client, name, parent, **extra):
    response = post_account(client, {"name": name, "parent_id": parent, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def tx(client, postings, **extra):
    response = client.post("/api/transactions/", json={"postings": postings, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def line(account, side, amount, **extra):
    return leg(account, side, amount, **extra)


@pytest.fixture
def rich(client, root_accounts):
    """A ledger that uses every feature a backup has to carry."""
    client.patch("/api/profile/", json={"first_name": "Ada", "last_name": "L", "default_currency": "INR"})
    banks = acct(client, "Banks", root_accounts["Assets"])
    bank = acct(client, "HDFC", banks["id"], balance="50000", details="main account")
    old = acct(client, "Old Savings", banks["id"])
    card = acct(client, "Visa", root_accounts["Liabilities"], on_budget=True)
    loan = acct(client, "Home Loan", root_accounts["Liabilities"], on_budget=False)
    food = acct(client, "Food", root_accounts["Expenses"])
    groceries = acct(client, "Groceries", food["id"])
    emi = acct(client, "EMI", root_accounts["Expenses"])
    salary = acct(client, "Salary", root_accounts["Income"])
    client.patch(f"/api/accounts/{loan['id']}", json={"payment_category_id": emi["id"]})
    assert client.post(f"/api/accounts/{old['id']}/close").status_code == 200

    dmart = tx(
        client,
        [line(groceries, "debit", "250"), line(card, "credit", "250")],
        date="2026-09-03",
        payee="DMart",
        tags=["weekly-shop", "food"],
    )
    tx(
        client,
        [line(card, "debit", "40"), line(groceries, "credit", "40")],
        date="2026-09-04",
        payee="DMart",
        related_id=dmart["id"],
        source="gmail",
        external_id="msg-9",
        source_url="https://mail.example.com/9",
    )
    tx(client, [line(bank, "debit", "90000"), line(salary, "credit", "90000")], date="2026-09-01", payee="Employer")
    tx(client, [line(loan, "debit", "15000"), line(bank, "credit", "15000")], date="2026-09-05", payee="EMI")
    tx(
        client,
        [line(groceries, "debit", "100"), line(food, "debit", "50"), line(bank, "credit", "150")],
        date="2026-09-06",
        comment="split",
    )

    client.post(
        "/api/recurring/",
        json={
            "from_account_id": bank["id"],
            **into(client, groceries),
            "amount": "500",
            "frequency": "monthly",
            "start_date": "2026-07-01",
            "payee": "Milk",
            "tags": ["milk-run", "weekly-shop"],
        },
    )
    client.post(
        "/api/recurring/",
        json={
            "postings": [line(groceries, "debit", "60"), line(food, "debit", "40"), line(bank, "credit", "100")],
            "frequency": "weekly",
            "start_date": "2999-01-01",
            "payee": "Split rule",
        },
    )
    recurring_id = next(r["id"] for r in client.get("/api/recurring/").json() if r["payee"] == "Split rule")
    assert (
        client.post(f"/api/recurring/{recurring_id}/skip").status_code == 200
    )  # a skipped occurrence is part of the rule's state
    client.put(f"/api/budget/categories/{groceries['id']}", json={"month": "2026-09-01", "amount": "3000"})
    client.put(f"/api/budget/categories/{emi['id']}", json={"month": "2026-09-01", "amount": "15000"})
    assert (
        client.post(
            "/budget/goal", data={"name": "Emergency fund", "amount": "100000", "by": "2999-12", "assign_now": "1"}
        ).status_code
        == 200
    )
    return {"bank": bank, "groceries": groceries}


def as_user(user_id):
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
        id=user_id, email="x@example.com", claims={}
    )


def canonical(doc: dict) -> dict:
    """A backup without ids and timestamps: accounts by path, everything pointing at them by path."""
    by_id = {a["id"]: a for a in doc["accounts"]}

    def path(account_id):
        names = []
        while account_id:
            names.append(by_id[account_id]["name"])
            account_id = by_id[account_id]["parent_id"]
        return ":".join(reversed(names))

    paths = {account_id: path(account_id) for account_id in by_id}
    cats = {c["id"]: c for c in doc["categories"]}
    for category_id, c in cats.items():
        group = cats.get(c["parent_id"])
        paths[category_id] = (
            ("Expenses" if c["kind"] == "spending" else "Income")
            + ":"
            + (f"{group['name']}:" if group else "")
            + c["name"]
        )
    rules = {r["id"]: (r["payee"], r["frequency"]) for r in doc["recurring"]}
    entries = {t["id"]: (t["date"], t["payee"], t["comment"]) for t in doc["transactions"]}
    return {
        "profile": doc["profile"],
        "accounts": sorted(
            (
                paths[a["id"]],
                a["details"],
                a["on_budget"],
                a["closed_on"] is not None,
                paths.get(a["payment_category_id"]),
            )
            for a in doc["accounts"]
        )
        + sorted(
            (paths[c["id"]], c["details"], c["closed_on"] is not None, c["system_key"]) for c in doc["categories"]
        ),
        "transactions": [
            (
                t["date"],
                t["payee"],
                t["comment"],
                t["created_via"],
                rules.get(t["recurring_id"]),
                t["recurring_date"],
                entries.get(t["related_id"]),
                (t["source"], t["external_id"], t["source_url"]),
                tuple(t["tags"]),
                sorted((paths[p["account"]], p["side"], p["amount"], paths.get(p["category"])) for p in t["postings"]),
            )
            for t in doc["transactions"]
        ],
        "recurring": sorted(
            (
                r["payee"],
                paths.get(r["from_account"]),
                paths.get(r["to_account"]),
                r["amount"],
                sorted((paths[p["account"]], p["side"], p["amount"], paths.get(p["category"])) for p in r["postings"]),
                tuple(r["tags"]),
                r["frequency"],
                r["start_date"],
                r["next_date"],
                r["last_date"],
                r["skipped_date"],
                r["active"],
            )
            for r in doc["recurring"]
        ),
        "allocations": sorted((a["month"], paths[a["category_id"]], a["amount"]) for a in doc["allocations"]),
        "goals": sorted(
            (g["name"], g["amount"], g["target_date"], sorted((r["month"], r["amount"]) for r in g["allocations"]))
            for g in doc["goals"]
        ),
    }


def test_the_backup_has_everything(client, rich):
    response = client.get("/api/backup")
    assert (
        response.status_code == 200
        and 'attachment; filename="finode-backup-' in response.headers["content-disposition"]
    )
    doc = response.json()
    assert doc["format"] == "finode-backup" and doc["version"] == 5
    assert doc["profile"]["first_name"] == "Ada" and doc["profile"]["default_currency"] == "INR"
    names = {a["name"] for a in doc["accounts"]}
    assert {
        "Banks",
        "HDFC",
        "Old Savings",
        "Visa",
        "Home Loan",
        "Opening Balances",
        "Assets",
    } <= names
    assert {"Groceries", "EMI"} <= {c["name"] for c in doc["categories"]} and "Groceries" not in names
    assert any(a["closed_on"] for a in doc["accounts"]) and any(a["payment_category_id"] for a in doc["accounts"])
    assert any(a["on_budget"] for a in doc["accounts"])
    assert len(doc["recurring"]) == 2 and any(r["postings"] for r in doc["recurring"])
    assert any(t["recurring_id"] for t in doc["transactions"]), "recorded occurrences keep their rule"
    assert len(doc["allocations"]) == 2
    assert [g["name"] for g in doc["goals"]] == ["Emergency fund"] and len(doc["goals"][0]["allocations"]) == 1, (
        "goals are their own records"
    )
    assert set(doc) == {
        "format",
        "version",
        "exported_at",
        "profile",
        "accounts",
        "categories",
        "transactions",
        "recurring",
        "allocations",
        "goals",
    }, "no tokens or connected apps"
    assert not any("commodity" in a for a in doc["accounts"]) and not any(
        "value" in p for t in doc["transactions"] for p in t["postings"]
    )


def test_restoring_rebuilds_the_same_books_for_someone_else(client, rich):
    doc = client.get("/api/backup").json()
    try:
        as_user(OTHER)
        assert client.get("/api/backup").json()["transactions"] == []
        preview = client.post(
            "/api/restore", params={"dry_run": True}, files={"file": ("b.json", json.dumps(doc), "application/json")}
        )
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


def test_an_older_backup_with_pinned_accounts_still_restores(client, rich):
    doc = client.get("/api/backup").json()
    for account in doc["accounts"]:
        account["pinned"] = True  # files from before pinning was removed carry the flag
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 200, done.text
        assert not any("pinned" in a for a in client.get("/api/backup").json()["accounts"]), "read, never written"
    finally:
        as_user(TEST_USER_ID)


def test_an_older_backup_with_a_lock_and_hand_set_places_still_restores(client, rich):
    doc = client.get("/api/backup").json()
    doc["profile"]["locked_through"] = "2026-08-31"  # the period lock and the account order were removed (2026-10-25)
    for place, account in enumerate(doc["accounts"]):
        account["position"] = place
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 200, done.text
        again = client.get("/api/backup").json()
        assert "locked_through" not in again["profile"] and not any("position" in a for a in again["accounts"]), (
            "read, never written"
        )
    finally:
        as_user(TEST_USER_ID)


def test_an_older_backup_with_build_and_earn_rows_restores_without_them(client, rich):
    """Files from when the Plan had Build and Earn carry plan rows for a fund and for an income account: the budget keeps
    only the expense categories' rows, and the flags the file carries are ignored."""
    doc = client.get("/api/backup").json()
    fund = next(a for a in doc["accounts"] if a["name"] == "Home Loan")
    salary = next(a for a in doc["accounts"] if a["name"] == "Assets" and a["parent_id"] is None)
    fund["saving"] = True
    doc["profile"].update(plan_build=True, plan_earn=True)
    for account in (fund, salary):
        doc["allocations"].append({"month": "2026-09-01", "category_id": account["id"], "amount": "700"})
    doc["targets"] = [
        {"account_id": fund["id"], "kind": "monthly", "amount": "700", "target_date": None, "weekday": None}
    ]  # a file from before targets were removed
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 200, done.text
        again = client.get("/api/backup").json()
    finally:
        as_user(TEST_USER_ID)
    assert len(again["allocations"]) == 2 and "targets" not in again, "old targets are read and dropped"
    assert not any("saving" in a for a in again["accounts"]) and "plan_build" not in again["profile"]


def test_a_restore_is_only_for_an_empty_ledger(client, rich):
    doc = client.get("/api/backup").json()
    refused = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
    assert refused.status_code == 400 and "empty ledger" in str(refused.json()["detail"])


def test_a_broken_file_is_refused_and_saves_nothing(client, rich):
    doc = client.get("/api/backup").json()
    try:
        as_user(OTHER)

        def post(body):
            return client.post(
                "/api/restore",
                files={"file": ("b.json", body if isinstance(body, str) else json.dumps(body), "application/json")},
            )

        assert post("not json").status_code == 400
        assert (
            post({"format": "other", "version": 1, "profile": {"default_currency": "INR"}, "accounts": []}).status_code
            == 400
        )
        wrong_version = {**doc, "version": 99}
        assert "version 99" in str(post(wrong_version).json())
        unbalanced = json.loads(json.dumps(doc))
        unbalanced["transactions"][0]["postings"][0]["amount"] = "1"
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
    assert "only works on an empty ledger" in page
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


# ---- backups made before finode kept one currency (version 1) ---------------------------------------------------------


def as_version_1(doc: dict) -> dict:
    """What an older finode wrote: a currency per transaction, a worth per posting, a commodity per account."""
    old = json.loads(json.dumps(doc))
    old["version"] = 1
    old["commodities"], old["prices"] = [], []
    for a in old["accounts"]:
        a["commodity"] = "INR" if a["parent_id"] else None
    for t in old["transactions"]:
        t["currency"] = "INR"
        for p in t["postings"]:
            p["value"] = p["amount"]
    for r in old["recurring"]:
        r["currency"] = None
        for p in r["postings"]:
            p["value"] = None
    return old


def restore_as_other(client, doc):
    try:
        as_user(OTHER)
        return client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
    finally:
        as_user(TEST_USER_ID)


def test_an_old_single_currency_backup_still_restores(client, rich):
    doc = client.get("/api/backup").json()
    response = restore_as_other(client, as_version_1(doc))
    assert response.status_code == 200, response.text
    assert response.json()["transactions"] == len(doc["transactions"])


def test_an_old_backup_with_own_assets_or_prices_is_refused_and_explained(client, rich):
    old = as_version_1(client.get("/api/backup").json())
    old["commodities"] = [{"code": "BTC", "name": "Bitcoin", "kind": "crypto", "decimals": 8}]
    refused = restore_as_other(client, old)
    assert refused.status_code == 400 and "one currency" in str(refused.json())


def test_an_old_backup_in_another_currency_is_refused_and_explained(client, rich):
    old = as_version_1(client.get("/api/backup").json())
    old["transactions"][0]["currency"] = "USD"
    refused = restore_as_other(client, old)
    assert refused.status_code == 400 and "USD" in str(refused.json()) and "one currency" in str(refused.json())
    converting = as_version_1(client.get("/api/backup").json())
    converting["transactions"][0]["postings"][0]["value"] = "1"
    assert restore_as_other(client, converting).status_code == 400


def test_a_backup_carries_tags_and_a_restore_makes_them(client, rich):
    doc = client.get("/api/backup").json()
    tagged = [t for t in doc["transactions"] if t["tags"] and not t["recurring_id"]]
    assert tagged and sorted(tagged[0]["tags"]) == ["food", "weekly-shop"]
    assert [r["tags"] for r in doc["recurring"] if r["payee"] == "Milk"] == [["milk-run", "weekly-shop"]]
    try:
        as_user(OTHER)
        preview = client.post(
            "/api/restore", params={"dry_run": "true"}, files={"file": ("b.json", json.dumps(doc), "application/json")}
        )
        assert preview.json()["tags"] == 3  # the entries' tags and the rule's ("milk-run" comes from its entries)
        assert (
            client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")}).status_code
            == 200
        )
        assert sorted(t["tag"] for t in client.get("/api/tags/").json()) == ["food", "milk-run", "weekly-shop"]
        assert [r["tags"] for r in client.get("/api/recurring/").json() if r["payee"] == "Milk"] == [
            ["milk-run", "weekly-shop"]
        ]
    finally:
        as_user(TEST_USER_ID)


def test_an_older_backup_with_tags_in_its_notes_restores_them_as_tags(client, rich):
    doc = client.get("/api/backup").json()
    doc["version"] = 2
    for t in doc["transactions"]:
        t.pop("tags")
        if t["payee"] == "DMart" and t["date"] == "2026-09-03":
            t["comment"] = "Weekly shop #Weekly-Shop #food and #1 is no tag"
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 200, done.text
        entry = next(
            t for t in client.get("/api/transactions/").json() if t["payee"] == "DMart" and t["date"] == "2026-09-03"
        )
        assert entry["tags"] == ["food", "weekly-shop"] and entry["comment"] == "Weekly shop and #1 is no tag"
    finally:
        as_user(TEST_USER_ID)


def test_a_backup_with_a_bad_tag_is_refused(client, rich):
    doc = client.get("/api/backup").json()
    doc["transactions"][0]["tags"] = ["not valid"]
    try:
        as_user(OTHER)
        refused = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert refused.status_code == 400 and "cannot be a tag" in refused.text
    finally:
        as_user(TEST_USER_ID)
