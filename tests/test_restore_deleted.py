"""Bringing back a deleted entry: the page lists what was deleted, Restore puts it back exactly as it was."""

from datetime import timedelta

import pytest

from app.clock import local_today


@pytest.fixture
def ledger(client, root_accounts):
    def make(name, parent, **extra):
        return client.post("/api/accounts/", json={"name": name, "parent_id": parent, **extra}).json()["aid"]

    return make("Bank", root_accounts["Assets"], balance="5000"), make("Food", root_accounts["Expenses"])


def record(client, bank, food, payee="Lunch", amount="120", on=None, **extra):
    r = client.post("/api/transactions/", json={"date": str(on or local_today()), "payee": payee, "comment": "with notes", "postings": [
        {"account": food, "side": "debit", "amount": amount}, {"account": bank, "side": "credit", "amount": amount}], **extra})
    assert r.status_code == 201, r.text
    return r.json()["tid"]


def hid_of(client, tid):
    return next(d["hid"] for d in client.get("/api/transactions/deleted").json() if d["transaction"] == tid)


def test_a_deleted_entry_is_listed_and_restored_as_it_was(client, ledger):
    bank, food = ledger
    tid = record(client, bank, food, on=local_today() - timedelta(days=3))
    before = client.get(f"/api/transactions/{tid}").json()
    assert client.delete(f"/api/transactions/{tid}").status_code in (200, 204)
    assert client.get(f"/api/transactions/{tid}").status_code == 404
    page = client.get("/transactions/deleted").text
    assert "Lunch" in page and "120.00" in page and "Restore" in page
    back = client.post(f"/api/transactions/deleted/{hid_of(client, tid)}/restore")
    assert back.status_code == 201
    after = client.get(f"/api/transactions/{tid}").json()
    assert after["tid"] == tid, "the same id"
    for key in ("date", "payee", "comment"):
        assert after[key] == before[key]
    assert sorted((p["account"], p["side"], p["amount"]) for p in after["postings"]) == sorted(
        (p["account"], p["side"], p["amount"]) for p in before["postings"])
    assert client.get("/api/reports/trial-balance").json()["balanced"] is True
    assert "Lunch" not in client.get("/transactions/deleted").text, "what is back leaves the list"
    assert [h["action"] for h in client.get(f"/api/transactions/{tid}/history").json()] == ["created", "deleted", "created"]


def test_the_web_button_restores_and_says_so(client, ledger):
    bank, food = ledger
    tid = record(client, bank, food)
    client.delete(f"/api/transactions/{tid}")
    done = client.post(f"/transactions/deleted/{hid_of(client, tid)}/restore")
    assert done.status_code == 200 and done.headers["HX-Redirect"] == "/transactions/deleted"
    assert client.get(f"/api/transactions/{tid}").status_code == 200


def test_restoring_twice_or_something_unknown_is_refused(client, ledger):
    bank, food = ledger
    tid = record(client, bank, food)
    client.delete(f"/api/transactions/{tid}")
    hid = hid_of(client, tid)
    assert client.post(f"/api/transactions/deleted/{hid}/restore").status_code == 201
    again = client.post(f"/api/transactions/deleted/{hid}/restore")
    assert again.status_code == 400 and "already back" in again.json()["detail"]
    assert client.post("/api/transactions/deleted/00000000-0000-4000-8000-000000000000/restore").status_code == 404
    web = client.post("/transactions/deleted/00000000-0000-4000-8000-000000000000/restore")
    assert web.status_code == 404 and web.headers["HX-Retarget"] == "#restore-error"


def test_only_the_latest_deletion_of_an_entry_can_be_restored(client, ledger):
    bank, food = ledger
    tid = record(client, bank, food)
    client.delete(f"/api/transactions/{tid}")
    first = hid_of(client, tid)
    client.post(f"/api/transactions/deleted/{first}/restore")
    client.patch(f"/api/transactions/{tid}", json={"payee": "Changed"})
    client.delete(f"/api/transactions/{tid}")
    old = client.post(f"/api/transactions/deleted/{first}/restore")
    assert old.status_code == 400
    listed = client.get("/transactions/deleted").text
    assert listed.count("Changed") == 1 and "Lunch" not in listed, "one row per entry, the latest state"


def test_an_account_that_is_gone_blocks_the_restore_with_a_reason(client, ledger):
    bank, food = ledger
    other = client.post("/api/accounts/", json={"name": "Snacks", "parent_id": client.get(f"/api/accounts/{food}").json()["parent_id"]}).json()["aid"]
    tid = record(client, bank, other)
    client.delete(f"/api/transactions/{tid}")
    assert client.delete(f"/api/accounts/{other}").status_code in (200, 204)
    refused = client.post(f"/api/transactions/deleted/{hid_of(client, tid)}/restore")
    assert refused.status_code == 400 and "no longer exists" in refused.json()["detail"]


def test_a_locked_period_blocks_the_restore(client, ledger):
    bank, food = ledger
    tid = record(client, bank, food, on=local_today() - timedelta(days=10))
    client.delete(f"/api/transactions/{tid}")
    client.patch("/api/profile/", json={"locked_through": str(local_today() - timedelta(days=5))})
    assert client.post(f"/api/transactions/deleted/{hid_of(client, tid)}/restore").status_code == 400


def test_the_transactions_page_links_to_the_deleted_page(client):
    assert 'href="/transactions/deleted"' in client.get("/transactions").text


def test_nothing_deleted_says_so(client):
    assert "Nothing deleted" in client.get("/transactions/deleted").text
