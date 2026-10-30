"""Bringing back a deleted entry: the page lists what was deleted, Restore puts it back exactly as it was."""

from datetime import timedelta
from uuid import UUID

import pytest

from app.clock import local_today

from .books import post_account


@pytest.fixture
def ledger(client, root_accounts):
    def make(name, parent, **extra):
        return post_account(client, {"name": name, "parent_id": parent, **extra}).json()["aid"]

    return make("Bank", root_accounts["Assets"], balance="5000"), make("Food", root_accounts["Expenses"])


def record(client, bank, food, payee="Lunch", amount="120", on=None, **extra):
    r = client.post(
        "/api/transactions/",
        json={
            "date": str(on or local_today()),
            "payee": payee,
            "comment": "with notes",
            "postings": [
                {"account": food, "side": "debit", "amount": amount},
                {"account": bank, "side": "credit", "amount": amount},
            ],
            **extra,
        },
    )
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
        (p["account"], p["side"], p["amount"]) for p in before["postings"]
    )
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
    assert (
        again.status_code == 400 and "already back" in again.text and again.headers["HX-Retarget"] == "#restore-error"
    )
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
    other = client.post(
        "/api/accounts/", json={"name": "Snacks", "parent_id": client.get(f"/api/accounts/{food}").json()["parent_id"]}
    ).json()["aid"]
    tid = record(client, bank, other)
    client.delete(f"/api/transactions/{tid}")
    assert client.delete(f"/api/accounts/{other}").status_code in (200, 204)
    refused = restore(client, hid_of(svc, tid))
    assert refused.status_code == 400 and "no longer exists" in refused.text


def test_the_deleted_page_is_reached_from_settings_and_leads_back_there(client):
    assert 'href="/accounts/deleted"' in client.get("/settings").text
    page = client.get("/transactions/deleted").text
    assert 'href="/settings"' in page and 'class="back" href="/transactions"' not in page


def test_nothing_deleted_says_so(client):
    assert "Nothing deleted" in client.get("/transactions/deleted").text


# ---- related links -------------------------------------------------------------------------------------------------


def related_of(client, tid):
    return client.get(f"/api/transactions/{tid}").json()["related_id"]


def test_a_restored_entry_is_related_to_the_same_earlier_entry_again(client, ledger, svc):
    bank, food = ledger
    original = record(client, bank, food, "Shop")
    refund = record(client, bank, food, "Shop refund", related_id=original)
    client.delete(f"/api/transactions/{refund}")
    assert restore(client, hid_of(svc, refund)).status_code == 200
    assert related_of(client, refund) == original
    assert [t["tid"] for t in client.get(f"/api/transactions/{original}/related").json()] == [refund]


def test_entries_that_pointed_at_a_restored_one_point_at_it_again(client, ledger, svc):
    bank, food = ledger
    original = record(client, bank, food, "Shop")
    refund = record(client, bank, food, "Refund", related_id=original)
    other = record(client, bank, food, "Other refund", related_id=original)
    client.delete(f"/api/transactions/{original}")
    assert related_of(client, refund) is None and related_of(client, other) is None, "deleting unlinks them"
    assert restore(client, hid_of(svc, original)).status_code == 200
    assert related_of(client, refund) == original and related_of(client, other) == original


def test_a_link_is_not_restored_when_it_would_be_wrong(client, ledger, svc):
    bank, food = ledger
    original = record(client, bank, food, "Shop")
    refund = record(client, bank, food, "Refund", related_id=original)
    # the earlier entry is gone: the restored refund is simply not related to anything
    client.delete(f"/api/transactions/{refund}")
    client.delete(f"/api/transactions/{original}")
    assert restore(client, hid_of(svc, refund)).status_code == 200
    assert related_of(client, refund) is None
    # an entry that got another link meanwhile keeps it; so does one that would make a circle
    a = record(client, bank, food, "A")
    b = record(client, bank, food, "B", related_id=a)
    c = record(client, bank, food, "C", related_id=b)
    client.delete(f"/api/transactions/{b}")  # c is unlinked
    assert client.patch(f"/api/transactions/{a}", json={"related_id": c}).status_code == 200  # a -> c
    assert (
        restore(client, hid_of(svc, b)).status_code == 200
    )  # b -> a; c would point at b: c -> b -> a -> c is a circle
    assert related_of(client, b) == a and related_of(client, c) is None
    other = record(client, bank, food, "Own link")
    d = record(client, bank, food, "D", related_id=other)
    client.delete(f"/api/transactions/{other}")
    e = record(client, bank, food, "E")
    assert client.patch(f"/api/transactions/{d}", json={"related_id": e}).status_code == 200
    assert restore(client, hid_of(svc, other)).status_code == 200
    assert related_of(client, d) == e, "it keeps the link it has now"


def test_history_notes_a_changed_link_but_not_an_unchanged_one(client, ledger, svc):
    bank, food = ledger
    a = record(client, bank, food, "A")
    b = record(client, bank, food, "B")
    client.patch(f"/api/transactions/{b}", json={"payee": "B"})  # nothing changed
    assert [h.action for h in svc.transactions.history(UUID(b))] == ["created"]
    client.patch(f"/api/transactions/{b}", json={"related_id": a})
    assert [h.action for h in svc.transactions.history(UUID(b))] == ["created", "updated"]
