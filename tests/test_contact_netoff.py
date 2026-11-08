"""Netting off what two people owe each other: the same amount cleared on both sides, no money moves."""

import json

import pytest

from .conftest import TEST_USER_ID

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "100000"}
    ).json()


@pytest.fixture
def alice(client):
    return client.post("/api/contacts/", json={"name": "Alice"}).json()


def transfer(client, who, bank, direction, purpose, amount, day="2026-10-01"):
    made = client.post(
        f"/api/contacts/{who['id']}/transfers",
        json={"direction": direction, "purpose": purpose, "amount": amount, "account_id": bank["id"], "date": day},
    )
    assert made.status_code == 201, made.text
    return made.json()


def balance(client, account_id):
    return float(client.get(f"/api/accounts/{account_id}").json()["balance"])


def open_amounts(client, who, direction):
    rows = client.get(
        f"/api/contacts/{who['id']}/obligations", params={"direction": direction, "open_only": True}
    ).json()
    return [float(o["outstanding_amount"]) for o in rows]


def test_a_loan_and_a_borrowing_of_the_same_size_clear_each_other(client, bank, alice):
    transfer(client, alice, bank, "sent", "loan", "23000", "2026-10-01")
    transfer(client, alice, bank, "received", "borrowing", "23000", "2026-10-03")
    cash = balance(client, bank["id"])
    budget = client.get("/api/budget/").json()["ready_to_assign"]
    made = client.post(f"/api/contacts/{alice['id']}/net-off")
    assert made.status_code == 201, made.text
    body = made.json()
    assert float(body["amount"]) == 23000 and body["id"]
    assert [float(a["amount"]) for a in body["receivables"]] == [23000] and [
        float(a["amount"]) for a in body["payables"]
    ] == [23000]
    assert float(body["receivable_left"]) == 0 and float(body["payable_left"]) == 0
    assert balance(client, alice["receivable_account_id"]) == 0 and balance(client, alice["payable_account_id"]) == 0
    assert balance(client, bank["id"]) == cash and client.get("/api/budget/").json()["ready_to_assign"] == budget
    assert open_amounts(client, alice, "receivable") == [] and open_amounts(client, alice, "payable") == []
    summary = client.get(f"/api/contacts/{alice['id']}/summary").json()
    assert summary["open_obligations"] == 0 and float(summary["net_balance"]) == 0
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    assert client.get(f"/api/net-offs/{body['id']}").json()["id"] == body["id"]
    assert client.get(f"/api/contacts/{alice['id']}/activity").json()["items"][0]["purpose"] == "netoff"


def test_the_smaller_side_clears_in_full_oldest_first(client, bank, alice):
    transfer(client, alice, bank, "sent", "loan", "5000", "2026-09-01")
    transfer(client, alice, bank, "sent", "loan", "6000", "2026-09-10")
    transfer(client, alice, bank, "received", "borrowing", "7000", "2026-09-20")
    preview = client.get(f"/api/contacts/{alice['id']}/net-off")
    assert preview.status_code == 200 and preview.json()["id"] is None
    assert float(preview.json()["amount"]) == 7000
    assert open_amounts(client, alice, "receivable") == [5000.0, 6000.0], "a preview saves nothing"
    made = client.post(f"/api/contacts/{alice['id']}/net-off").json()
    assert [float(a["amount"]) for a in made["receivables"]] == [5000, 2000], "the older loan first"
    assert [float(a["amount"]) for a in made["payables"]] == [7000]
    assert open_amounts(client, alice, "receivable") == [4000.0] and open_amounts(client, alice, "payable") == []
    assert float(made["receivable_left"]) == 4000
    contact = client.get(f"/api/contacts/{alice['id']}").json()
    assert float(contact["receivable"]) == 4000 and float(contact["payable"]) == 0


def test_it_needs_something_owed_both_ways(client, bank, alice):
    refused = client.post(f"/api/contacts/{alice['id']}/net-off")
    assert refused.status_code == 400 and "each way" in refused.json()["detail"]
    transfer(client, alice, bank, "sent", "loan", "50")
    assert client.post(f"/api/contacts/{alice['id']}/net-off").status_code == 400
    assert client.get(f"/api/contacts/{alice['id']}/net-off").status_code == 400
    assert client.post(f"/api/contacts/{MISSING}/net-off").status_code == 404
    assert client.get(f"/api/net-offs/{MISSING}").status_code == 404


def test_it_can_be_reversed(client, bank, alice):
    transfer(client, alice, bank, "sent", "loan", "300")
    transfer(client, alice, bank, "received", "borrowing", "300")
    made = client.post(f"/api/contacts/{alice['id']}/net-off").json()
    assert client.delete(f"/api/net-offs/{made['id']}").status_code == 204
    assert open_amounts(client, alice, "receivable") == [300.0] and open_amounts(client, alice, "payable") == [300.0]
    assert (
        balance(client, alice["receivable_account_id"]) == 300 and balance(client, alice["payable_account_id"]) == 300
    )
    assert client.get(f"/api/transactions/{made['id']}").status_code == 404
    assert client.delete(f"/api/net-offs/{made['id']}").status_code == 404


def test_the_entry_belongs_to_the_person_and_a_retry_nets_off_once(client, bank, alice):
    transfer(client, alice, bank, "sent", "loan", "300")
    transfer(client, alice, bank, "received", "borrowing", "100")
    url = f"/api/contacts/{alice['id']}/net-off"
    first = client.post(url, headers={"Idempotency-Key": "n1"})
    again = client.post(url, headers={"Idempotency-Key": "n1"})
    assert first.status_code == 201 and again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert open_amounts(client, alice, "receivable") == [200.0]
    assert client.delete(f"/api/transactions/{first.json()['id']}").status_code == 400, (
        "only the person's page reverses it"
    )


def test_a_net_off_is_in_the_backup(client, bank, alice):
    from .test_backup import OTHER, as_user

    transfer(client, alice, bank, "sent", "loan", "300")
    transfer(client, alice, bank, "received", "borrowing", "300")
    client.post(f"/api/contacts/{alice['id']}/net-off")
    doc = client.get("/api/backup").json()
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 200, done.text
        again = client.get("/api/contacts/").json()[0]
        assert float(again["receivable"]) == 0 and float(again["payable"]) == 0
        assert client.get(f"/api/contacts/{again['id']}/summary").json()["open_obligations"] == 0
    finally:
        as_user(TEST_USER_ID)
