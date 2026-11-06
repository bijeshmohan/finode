"""Contacts: people with two ledger accounts behind them, "Due from X" and "Due to X"."""

import pytest

from .books import leg

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "1000"}
    ).json()


def make(client, name="Alice", **extra):
    response = client.post("/api/contacts/", json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def account(client, account_id):
    response = client.get(f"/api/accounts/{account_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_contact_gets_its_two_accounts(client, root_accounts):
    alice = make(client, email=" a@example.com ", phone="", notes="college friend")
    assert alice["name"] == "Alice" and alice["email"] == "a@example.com" and alice["phone"] is None
    assert alice["archived"] is False
    due_from, due_to = account(client, alice["receivable_account_id"]), account(client, alice["payable_account_id"])
    assert due_from["name"] == "Due from Alice" and due_from["parent_id"] == root_accounts["Assets"]
    assert due_to["name"] == "Due to Alice" and due_to["parent_id"] == root_accounts["Liabilities"]
    assert due_from["on_budget"] is False and due_to["on_budget"] is False, "money owed is not money in the budget"


def test_names_are_unique_clean_and_short(client):
    make(client)
    for name in ("alice", "  ALICE "):
        assert client.post("/api/contacts/", json={"name": name}).status_code == 400
    for name in ("", "   ", "A:B", "x" * 31):
        assert client.post("/api/contacts/", json={"name": name}).status_code == 422
    assert make(client, "x" * 30)["name"] == "x" * 30, "30 characters fit in 'Due from …'"


def test_a_name_an_account_already_has_is_refused_and_nothing_is_left_behind(client, root_accounts):
    client.post("/api/accounts/", json={"name": "Due to Bob", "parent_id": root_accounts["Liabilities"]})
    assert client.post("/api/contacts/", json={"name": "Bob"}).status_code == 400
    assert client.get("/api/contacts/").json() == []
    names = [a["name"] for a in client.get("/api/accounts/").json()]
    assert "Due from Bob" not in names, "the first account was rolled back with the second"


def test_list_get_and_update(client):
    make(client, "Zed")
    alice = make(client)
    assert [c["name"] for c in client.get("/api/contacts/").json()] == ["Alice", "Zed"]
    assert client.get(f"/api/contacts/{alice['id']}").json()["id"] == alice["id"]
    assert client.get(f"/api/contacts/{MISSING}").status_code == 404
    changed = client.patch(f"/api/contacts/{alice['id']}", json={"notes": "moved", "phone": "99"})
    assert changed.json()["notes"] == "moved" and changed.json()["phone"] == "99"
    assert client.patch(f"/api/contacts/{alice['id']}", json={"notes": None}).json()["notes"] is None
    assert client.patch(f"/api/contacts/{MISSING}", json={"notes": "x"}).status_code == 404
    assert client.patch(f"/api/contacts/{alice['id']}", json={"name": None}).status_code == 422


def test_renaming_a_contact_renames_both_accounts(client):
    alice = make(client)
    make(client, "Bob")
    assert client.patch(f"/api/contacts/{alice['id']}", json={"name": "Bob"}).status_code == 400
    renamed = client.patch(f"/api/contacts/{alice['id']}", json={"name": "Alicia"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Alicia"
    assert account(client, alice["receivable_account_id"])["name"] == "Due from Alicia"
    assert account(client, alice["payable_account_id"])["name"] == "Due to Alicia"


def test_the_two_accounts_cannot_be_changed_from_the_accounts_side(client, root_accounts):
    alice = make(client)
    due_from = alice["receivable_account_id"]
    other = client.post("/api/accounts/", json={"name": "Wallet", "parent_id": root_accounts["Assets"]}).json()
    assert client.patch(f"/api/accounts/{due_from}", json={"name": "Hacked"}).status_code == 400
    assert client.post(f"/api/accounts/{due_from}/close").status_code == 400
    assert client.delete(f"/api/accounts/{due_from}").status_code == 400
    assert client.post(f"/api/accounts/{other['id']}/merge", json={"into": due_from}).status_code == 400
    assert client.post(f"/api/accounts/{due_from}/merge", json={"into": other["id"]}).status_code == 400
    assert account(client, due_from)["name"] == "Due from Alice"


def test_a_contact_nobody_dealt_with_is_deleted_with_its_accounts(client):
    alice = make(client)
    done = client.delete(f"/api/contacts/{alice['id']}")
    assert done.status_code == 200 and done.json()["outcome"] == "deleted"
    assert client.get(f"/api/contacts/{alice['id']}").status_code == 404
    assert client.get(f"/api/accounts/{alice['receivable_account_id']}").status_code == 404
    assert client.get(f"/api/accounts/{alice['payable_account_id']}").status_code == 404
    assert make(client)["name"] == "Alice", "the name is free again"


def lend(client, contact, bank, amount="300"):
    """Phase 2 does this through the transfer service; for now a plain entry puts money on 'Due from'."""
    response = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account_id": contact["receivable_account_id"], "side": "debit", "amount": amount},
                leg(bank, "credit", amount),
            ]
        },
    )
    assert response.status_code == 201, response.text


def test_a_contact_with_history_is_archived_only_once_nothing_is_owed(client, bank):
    alice = make(client)
    lend(client, alice, bank)
    refused = client.post(f"/api/contacts/{alice['id']}/archive")
    assert refused.status_code == 400 and "owes you 300" in refused.json()["detail"]
    kept = client.delete(f"/api/contacts/{alice['id']}")
    assert kept.status_code == 400, "deleting a contact with a debt is refused, not hidden"
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(bank, "debit", "300"),
                {"account_id": alice["receivable_account_id"], "side": "credit", "amount": "300"},
            ]
        },
    )
    gone = client.delete(f"/api/contacts/{alice['id']}")
    assert gone.status_code == 200 and gone.json()["outcome"] == "archived" and gone.json()["contact"]["archived"]
    assert [c["id"] for c in client.get("/api/contacts/").json()] == []
    listed = client.get("/api/contacts/", params={"include_archived": True}).json()
    assert [c["id"] for c in listed] == [alice["id"]] and listed[0]["archived_at"]
    assert client.get(f"/api/accounts/{alice['receivable_account_id']}").status_code == 200, "history stays"
    restored = client.post(f"/api/contacts/{alice['id']}/restore")
    assert restored.status_code == 200 and restored.json()["archived"] is False
    assert [c["id"] for c in client.get("/api/contacts/").json()] == [alice["id"]]


def test_archiving_twice_and_restoring_a_live_contact_change_nothing(client):
    alice = make(client)
    assert client.post(f"/api/contacts/{alice['id']}/restore").json()["archived"] is False
    assert client.post(f"/api/contacts/{alice['id']}/archive").json()["archived"] is True
    assert client.post(f"/api/contacts/{alice['id']}/archive").json()["archived"] is True
    assert client.post(f"/api/contacts/{MISSING}/archive").status_code == 404


def test_a_person_can_have_only_so_many_contacts(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "max_contacts", 1)
    make(client)
    refused = client.post("/api/contacts/", json={"name": "Bob"})
    assert refused.status_code == 400 and "limit of 1 contacts" in refused.json()["detail"]


def test_the_trial_balance_stays_balanced_with_contacts(client, bank):
    alice = make(client)
    lend(client, alice, bank)
    assert client.get("/api/reports/trial-balance").json()["balanced"] is True
