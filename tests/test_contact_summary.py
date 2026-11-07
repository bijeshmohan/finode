"""A contact's figures: the ledger is the authority, the records explain it; the list can be searched and sorted."""

import random
from decimal import Decimal

import pytest

from .books import category

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "100000"}
    ).json()


def contact(client, name, **extra):
    return client.post("/api/contacts/", json={"name": name, **extra}).json()


def transfer(client, who, bank, direction, purpose, amount, day="2026-10-01"):
    made = client.post(
        f"/api/contacts/{who['id']}/transfers",
        json={"direction": direction, "purpose": purpose, "amount": amount, "account_id": bank["id"], "date": day},
    )
    assert made.status_code == 201, made.text
    return made.json()


def test_the_summary_and_the_activity(client, bank):
    alice, bob = contact(client, "Alice"), contact(client, "Bob")
    dining = category(client, "Dining")
    transfer(client, alice, bank, "sent", "loan", "2000", "2026-10-01")
    transfer(client, alice, bank, "received", "borrowing", "300", "2026-10-02")
    transfer(client, alice, bank, "sent", "gift", "100", "2026-10-03")
    client.post(
        f"/api/contacts/{alice['id']}/settlements",
        json={"direction": "received", "amount": "500", "account_id": bank["id"], "date": "2026-10-04"},
    )
    client.post(
        "/api/shared-expenses/",
        params={"confirm": True},
        json={
            "description": "Dinner",
            "total_amount": "900",
            "date": "2026-10-05",
            "category_id": dining["id"],
            "participants": [{"is_self": True}, {"contact_id": alice["id"]}, {"contact_id": bob["id"]}],
            "payments": [{"account_id": bank["id"], "amount": "900"}],
        },
    )
    summary = client.get(f"/api/contacts/{alice['id']}/summary").json()
    assert float(summary["total_receivable"]) == 1800 and float(summary["total_payable"]) == 300
    assert float(summary["net_balance"]) == 1500
    assert float(summary["total_lent"]) == 2000 and float(summary["total_borrowed"]) == 300
    assert float(summary["total_expenses_shared"]) == 300 and float(summary["total_settlements"]) == 500
    assert summary["open_obligations"] == 3, "the rest of the loan, the borrowing and Alice's share of the dinner"
    assert [r["purpose"] for r in summary["recent"]] == ["expense", "settlement", "gift", "borrowing", "loan"]
    page = client.get(f"/api/contacts/{alice['id']}/activity").json()
    assert page["total"] == 5 and [i["purpose"] for i in page["items"]][0] == "expense"
    only = client.get(f"/api/contacts/{alice['id']}/activity", params={"purpose": "loan"}).json()
    assert only["total"] == 1 and float(only["items"][0]["amount"]) == 2000 and only["items"][0]["direction"] == "sent"
    two = client.get(f"/api/contacts/{alice['id']}/activity", params={"limit": 2, "offset": 1}).json()
    assert two["total"] == 5 and [i["purpose"] for i in two["items"]] == ["settlement", "gift"]
    assert client.get(f"/api/contacts/{alice['id']}/summary").status_code == 200
    assert client.get(f"/api/contacts/{MISSING}/summary").status_code == 404
    assert client.get(f"/api/contacts/{MISSING}/activity").status_code == 404
    assert client.get(f"/api/contacts/{alice['id']}/activity", params={"limit": 0}).status_code == 422


def test_the_list_carries_balances_and_can_be_searched_sorted_and_filtered(client, bank):
    alice = contact(client, "Alice", email="a@example.com")
    bob = contact(client, "Bob", notes="flatmate")
    carol = contact(client, "Carol")
    transfer(client, alice, bank, "sent", "loan", "100", "2026-10-01")
    transfer(client, bob, bank, "received", "borrowing", "900", "2026-10-02")
    listed = {c["name"]: c for c in client.get("/api/contacts/").json()}
    assert float(listed["Alice"]["net"]) == 100 and listed["Alice"]["last_activity"] == "2026-10-01"
    assert float(listed["Bob"]["payable"]) == 900 and float(listed["Bob"]["net"]) == -900
    assert listed["Carol"]["last_activity"] is None and float(listed["Carol"]["net"]) == 0

    def names(**params):
        return [c["name"] for c in client.get("/api/contacts/", params=params).json()]

    assert names() == ["Alice", "Bob", "Carol"]
    assert names(sort="balance") == ["Bob", "Alice", "Carol"], "the biggest amount outstanding first, either way"
    assert names(owing="receivable") == ["Alice"] and names(owing="payable") == ["Bob"]
    assert names(q="FLAT") == ["Bob"] and names(q="a@example") == ["Alice"] and names(q="zzz") == []
    assert names(q="  ") == ["Alice", "Bob", "Carol"]
    client.post(f"/api/contacts/{carol['id']}/archive")
    assert names() == ["Alice", "Bob"] and names(include_archived=True) == ["Alice", "Bob", "Carol"]


def test_the_balances_always_agree_with_the_obligations(client, bank):
    """After any run of operations: each side's ledger balance is exactly what is still owed on its obligations, and the
    books balance."""
    rng = random.Random(7)
    people = [contact(client, name) for name in ("Alice", "Bob", "Carol")]
    dining = category(client, "Dining")
    for step in range(40):
        who = rng.choice(people)
        kind = rng.choice(["loan", "borrow", "settle_in", "settle_out", "expense", "gift"])
        amount = str(rng.randint(1, 500))
        if kind == "loan":
            transfer(client, who, bank, "sent", rng.choice(["loan", "advance"]), amount)
        elif kind == "borrow":
            transfer(client, who, bank, "received", rng.choice(["borrowing", "advance"]), amount)
        elif kind == "gift":
            transfer(client, who, bank, rng.choice(["sent", "received"]), "gift", amount)
        elif kind in ("settle_in", "settle_out"):
            client.post(
                f"/api/contacts/{who['id']}/settlements",
                json={
                    "direction": "received" if kind == "settle_in" else "sent",
                    "amount": amount,
                    "account_id": bank["id"],
                    "excess_as": rng.choice(["gift", "borrowing" if kind == "settle_in" else "loan"]),
                },
            )
        else:
            client.post(
                "/api/shared-expenses/",
                params={"confirm": True},
                json={
                    "description": f"Meal {step}",
                    "total_amount": amount,
                    "category_id": dining["id"],
                    "split_method": rng.choice(["equal", "shares"]),
                    "participants": [{"is_self": True, "value": "1"}, {"contact_id": who["id"], "value": "2"}],
                    "payments": [{"account_id": bank["id"], "amount": amount}],
                },
            )
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    for who in people:
        fresh = client.get(f"/api/contacts/{who['id']}").json()
        rows = client.get(f"/api/contacts/{who['id']}/obligations").json()
        for side, account in (("receivable", "receivable"), ("payable", "payable")):
            left = sum((Decimal(o["outstanding_amount"]) for o in rows if o["direction"] == side), Decimal(0))
            assert left == Decimal(fresh[account]), (who["name"], side)
        for o in rows:
            assert Decimal(o["settled_amount"]) <= Decimal(o["original_amount"])
            assert Decimal(o["outstanding_amount"]) == Decimal(o["original_amount"]) - Decimal(o["settled_amount"])
