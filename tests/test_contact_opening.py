"""Opening balances for a person: what they already owed before finode, recorded against Opening Balances."""

import json

import pytest

from .conftest import TEST_USER_ID

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "10000"}
    ).json()


@pytest.fixture
def alice(client):
    return client.post("/api/contacts/", json={"name": "Alice"}).json()


def opening(client, who, direction="receivable", amount="4000", **extra):
    return client.post(
        f"/api/contacts/{who['id']}/opening-balance", json={"direction": direction, "amount": amount, **extra}
    )


def balance(client, account_id):
    return float(client.get(f"/api/accounts/{account_id}").json()["balance"])


def test_they_owe_you_from_before(client, bank, alice):
    before = client.get("/api/budget/").json()
    made = opening(client, alice, date="2026-01-01", description="Old loan")
    assert made.status_code == 201, made.text
    body = made.json()
    assert (
        body["purpose"] == "opening"
        and float(body["amount"]) == 4000
        and body["obligation_id"]
        and body["date"] == "2026-01-01"
    )
    assert body["account_id"] is None
    assert balance(client, alice["receivable_account_id"]) == 4000 and balance(client, bank["id"]) == 10000
    after = client.get("/api/budget/").json()
    assert after["ready_to_assign"] == before["ready_to_assign"] and after["lines"] == before["lines"], (
        "no budget moves"
    )
    owed = client.get(f"/api/contacts/{alice['id']}/obligations").json()
    assert [(o["source_type"], o["direction"], o["description"], float(o["outstanding_amount"])) for o in owed] == [
        ("opening", "receivable", "Old loan", 4000.0)
    ]
    entry = client.get(f"/api/transactions/{body['id']}").json()
    assert entry["payee"] == "Opening balance"
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_you_owe_them_from_before(client, alice):
    assert opening(client, alice, "payable", "250").status_code == 201
    assert balance(client, alice["payable_account_id"]) == 250
    summary = client.get(f"/api/contacts/{alice['id']}/summary").json()
    assert float(summary["net_balance"]) == -250 and summary["open_obligations"] == 1
    assert float(summary["total_lent"]) == 0 and float(summary["total_borrowed"]) == 0, (
        "it was neither lent nor borrowed now"
    )
    page = client.get(f"/api/contacts/{alice['id']}/activity").json()
    assert page["items"][0]["purpose"] == "opening" and page["items"][0]["direction"] == "received"


def test_it_is_settled_like_any_other_amount(client, bank, alice):
    opening(client, alice, date="2026-01-01")
    loan = client.post(
        f"/api/contacts/{alice['id']}/transfers",
        json={"direction": "sent", "purpose": "loan", "amount": "100", "account_id": bank["id"], "date": "2026-06-01"},
    )
    assert loan.status_code == 201
    paid = client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "4100", "account_id": bank["id"]},
    )
    assert paid.status_code == 201, paid.text
    assert [float(a["amount"]) for a in paid.json()["allocations"]] == [4000, 100], (
        "the older opening balance goes first"
    )
    assert balance(client, bank["id"]) == 14000
    assert float(client.get(f"/api/contacts/{alice['id']}").json()["net"]) == 0


def test_it_can_be_reversed_until_something_is_paid_against_it(client, bank, alice):
    made = opening(client, alice).json()
    paid = client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "10", "account_id": bank["id"]},
    ).json()
    assert client.delete(f"/api/transfers/{made['id']}").status_code == 409
    client.delete(f"/api/settlements/{paid['id']}")
    assert [t["id"] for t in client.get(f"/api/contacts/{alice['id']}/transfers").json()] == [made["id"]]
    assert client.delete(f"/api/transfers/{made['id']}").status_code == 204
    assert (
        balance(client, alice["receivable_account_id"]) == 0
        and client.get(f"/api/transactions/{made['id']}").status_code == 404
    )
    assert client.patch(f"/api/transactions/{made['id']}", json={"payee": "x"}).status_code == 404


def test_the_rules(client, alice):
    assert opening(client, alice, amount="0").status_code == 422
    assert opening(client, alice, direction="sideways").status_code == 422
    assert opening(client, {"id": MISSING}).status_code == 404
    entry = opening(client, alice).json()
    assert client.delete(f"/api/transactions/{entry['id']}").status_code == 400, "only the person's page reverses it"
    client.delete(f"/api/transfers/{entry['id']}")
    client.post(f"/api/contacts/{alice['id']}/archive")
    refused = opening(client, alice)
    assert refused.status_code == 400 and "archived" in refused.json()["detail"]


def test_a_retry_with_the_same_key_adds_it_once(client, alice):
    url = f"/api/contacts/{alice['id']}/opening-balance"
    body = {"direction": "receivable", "amount": "70", "date": "2026-01-01"}
    first = client.post(url, json=body, headers={"Idempotency-Key": "o1"})
    again = client.post(url, json=body, headers={"Idempotency-Key": "o1"})
    assert first.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert balance(client, alice["receivable_account_id"]) == 70
    assert client.post(url, json={**body, "amount": "71"}, headers={"Idempotency-Key": "o1"}).status_code == 409


def test_a_backup_brings_it_back(client, alice):
    from .test_backup import OTHER, as_user

    opening(client, alice, date="2026-01-01")
    doc = client.get("/api/backup").json()
    assert [o["source_type"] for o in doc["obligations"]] == ["opening"]
    try:
        as_user(OTHER)
        done = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
        assert done.status_code == 200, done.text
        again = client.get("/api/contacts/").json()[0]
        assert float(again["receivable"]) == 4000 and again["last_activity"] == "2026-01-01"
    finally:
        as_user(TEST_USER_ID)
