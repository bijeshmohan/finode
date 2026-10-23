"""Bringing back a deleted entry: the page lists what was deleted, Restore puts it back exactly as it was."""

from datetime import timedelta
from uuid import UUID

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


def hid_of(svc, tid):
    return next(d.hid for d in svc.transactions.deleted() if str(d.transaction) == tid)


def restore(client, hid):
    """Press Restore on the Recently deleted page."""
    return client.post(f"/transactions/deleted/{hid}/restore")


def restored(response) -> bool:
    return response.status_code == 200 and response.headers.get("HX-Redirect") == "/transactions/deleted"


def test_a_deleted_entry_is_listed_and_restored_as_it_was(client, ledger, svc):
    bank, food = ledger
    tid = record(client, bank, food, on=local_today() - timedelta(days=3))
    before = client.get(f"/api/transactions/{tid}").json()
    assert client.delete(f"/api/transactions/{tid}").status_code in (200, 204)
    assert client.get(f"/api/transactions/{tid}").status_code == 404
    page = client.get("/transactions/deleted").text
    assert "Lunch" in page and "120.00" in page and "Restore" in page
    assert restored(restore(client, hid_of(svc, tid)))
    after = client.get(f"/api/transactions/{tid}").json()
    assert after["tid"] == tid, "the same id"
    for key in ("date", "payee", "comment"):
        assert after[key] == before[key]
    assert sorted((p["account"], p["side"], p["amount"]) for p in after["postings"]) == sorted(
        (p["account"], p["side"], p["amount"]) for p in before["postings"])
    assert client.get("/api/reports/trial-balance").json()["balanced"] is True
    assert "Lunch" not in client.get("/transactions/deleted").text, "what is back leaves the list"
    assert [h.action for h in svc.transactions.history(UUID(tid))] == ["created", "deleted", "created"]


def test_the_web_button_restores_and_says_so(client, ledger, svc):
    bank, food = ledger
    tid = record(client, bank, food)
    client.delete(f"/api/transactions/{tid}")
    done = restore(client, hid_of(svc, tid))
    assert restored(done) and "transaction-restored" in done.headers["set-cookie"]
    assert client.get(f"/api/transactions/{tid}").status_code == 200


def test_restoring_twice_or_something_unknown_is_refused(client, ledger, svc):
    bank, food = ledger
    tid = record(client, bank, food)
    client.delete(f"/api/transactions/{tid}")
    hid = hid_of(svc, tid)
    assert restored(restore(client, hid))
    again = restore(client, hid)
    assert again.status_code == 400 and "already back" in again.text and again.headers["HX-Retarget"] == "#restore-error"
    web = restore(client, "00000000-0000-4000-8000-000000000000")
    assert web.status_code == 404 and web.headers["HX-Retarget"] == "#restore-error"


def test_only_the_latest_deletion_of_an_entry_can_be_restored(client, ledger, svc):
    bank, food = ledger
    tid = record(client, bank, food)
    client.delete(f"/api/transactions/{tid}")
    first = hid_of(svc, tid)
    restore(client, first)
    client.patch(f"/api/transactions/{tid}", json={"payee": "Changed"})
    client.delete(f"/api/transactions/{tid}")
    old = restore(client, first)
    assert old.status_code == 400
    listed = client.get("/transactions/deleted").text
    assert listed.count("Changed") == 1 and "Lunch" not in listed, "one row per entry, the latest state"


def test_an_account_that_is_gone_blocks_the_restore_with_a_reason(client, ledger, svc):
    bank, food = ledger
    other = client.post("/api/accounts/", json={"name": "Snacks", "parent_id": client.get(f"/api/accounts/{food}").json()["parent_id"]}).json()["aid"]
    tid = record(client, bank, other)
    client.delete(f"/api/transactions/{tid}")
    assert client.delete(f"/api/accounts/{other}").status_code in (200, 204)
    refused = restore(client, hid_of(svc, tid))
    assert refused.status_code == 400 and "no longer exists" in refused.text


def test_a_locked_period_blocks_the_restore(client, ledger, svc):
    bank, food = ledger
    tid = record(client, bank, food, on=local_today() - timedelta(days=10))
    client.delete(f"/api/transactions/{tid}")
    client.patch("/api/profile/", json={"locked_through": str(local_today() - timedelta(days=5))})
    assert restore(client, hid_of(svc, tid)).status_code == 400


def test_the_deleted_page_is_reached_from_settings_and_leads_back_there(client):
    assert 'href="/accounts/deleted"' in client.get("/settings").text
    page = client.get("/transactions/deleted").text
    assert 'href="/settings"' in page and 'class="back" href="/transactions"' not in page


def test_nothing_deleted_says_so(client):
    assert "Nothing deleted" in client.get("/transactions/deleted").text
