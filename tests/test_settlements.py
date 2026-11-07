"""Settling up with a contact: full, partial and several-at-once, oldest first or chosen, never beyond what is owed."""

import pytest

from .books import category

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "10000"}
    ).json()


@pytest.fixture
def alice(client):
    return client.post("/api/contacts/", json={"name": "Alice"}).json()


def balance(client, account_id):
    return float(client.get(f"/api/accounts/{account_id}").json()["balance"])


def lend(client, contact, bank, amount, day="2026-10-01", purpose="loan", direction="sent"):
    made = client.post(
        f"/api/contacts/{contact['id']}/transfers",
        json={"direction": direction, "purpose": purpose, "amount": amount, "account_id": bank["id"], "date": day},
    )
    assert made.status_code == 201, made.text
    return made.json()


def settle(client, contact, bank, amount, direction="received", **extra):
    return client.post(
        f"/api/contacts/{contact['id']}/settlements",
        json={"direction": direction, "amount": amount, "account_id": bank["id"], **extra},
    )


def owed(client, contact, **params):
    rows = client.get(f"/api/contacts/{contact['id']}/obligations", params=params).json()
    return [(o["description"] or o["source_type"], float(o["outstanding_amount"]), o["status"]) for o in rows]


@pytest.fixture
def three(client, bank, alice):
    """Three loans to Alice, oldest first: 500, 1000, 2000."""
    return [
        lend(client, alice, bank, "500", "2026-09-01"),
        lend(client, alice, bank, "1000", "2026-09-10"),
        lend(client, alice, bank, "2000", "2026-09-20"),
    ]


def test_a_full_repayment_clears_the_debt(client, bank, alice):
    lend(client, alice, bank, "500")
    made = settle(client, alice, bank, "500")
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["direction"] == "received" and float(body["amount"]) == 500 and float(body["excess"]) == 0
    assert balance(client, bank["id"]) == 10000 and balance(client, alice["receivable_account_id"]) == 0
    assert owed(client, alice) == [("loan", 0.0, "settled")]
    assert owed(client, alice, open_only=True) == []
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    assert client.get(f"/api/settlements/{body['id']}").json()["id"] == body["id"]
    assert [s["id"] for s in client.get(f"/api/contacts/{alice['id']}/settlements").json()] == [body["id"]]


def test_a_partial_repayment_leaves_the_rest(client, bank, alice):
    lend(client, alice, bank, "500")
    first = settle(client, alice, bank, "200").json()
    assert owed(client, alice) == [("loan", 300.0, "partially_settled")]
    assert [
        (float(a["outstanding_before"]), float(a["amount"]), float(a["outstanding_after"]))
        for a in first["allocations"]
    ] == [(500.0, 200.0, 300.0)]
    second = settle(client, alice, bank, "300").json()
    assert owed(client, alice) == [("loan", 0.0, "settled")]
    assert [(float(a["outstanding_before"]), float(a["outstanding_after"])) for a in second["allocations"]] == [
        (300.0, 0.0)
    ]


def test_fifo_clears_the_oldest_first_and_one_payment_can_clear_several(client, bank, alice, three):
    made = settle(client, alice, bank, "1700")
    assert made.status_code == 201, made.text
    assert [float(a["amount"]) for a in made.json()["allocations"]] == [500, 1000, 200]
    assert [o[1] for o in owed(client, alice)] == [0.0, 0.0, 1800.0]
    assert balance(client, alice["receivable_account_id"]) == 1800


def test_manual_allocation_chooses(client, bank, alice, three):
    ids = [t["obligation_id"] for t in three]
    made = settle(
        client,
        alice,
        bank,
        "700",
        allocation_method="manual",
        allocations=[{"obligation_id": ids[2], "amount": "500"}, {"obligation_id": ids[1], "amount": "200"}],
    )
    assert made.status_code == 201, made.text
    assert [o[1] for o in owed(client, alice)] == [500.0, 800.0, 1500.0]


def test_manual_allocation_is_checked(client, bank, alice, three):
    ids = [t["obligation_id"] for t in three]

    def manual(amount, allocations, **extra):
        return settle(client, alice, bank, amount, allocation_method="manual", allocations=allocations, **extra)

    assert manual("100", []).status_code == 400
    assert manual("100", [{"obligation_id": ids[0], "amount": "600"}]).status_code == 400, "more than that one owes"
    assert manual("100", [{"obligation_id": ids[0], "amount": "150"}]).status_code == 400, "more than the settlement"
    twice = [{"obligation_id": ids[0], "amount": "1"}] * 2
    assert manual("100", twice).status_code == 400
    assert manual("100", [{"obligation_id": MISSING, "amount": "1"}]).status_code == 404
    refused = manual("100", [{"obligation_id": ids[0], "amount": "50"}])
    assert refused.status_code == 400 and "say what the rest is" in refused.json()["detail"]
    assert (
        settle(client, alice, bank, "100", allocations=[{"obligation_id": ids[0], "amount": "100"}]).status_code == 400
    )
    assert [o[1] for o in owed(client, alice)] == [500.0, 1000.0, 2000.0], "nothing was cleared"


def test_nothing_goes_beyond_what_is_owed_unless_the_rest_is_named(client, bank, alice):
    lend(client, alice, bank, "500")
    refused = settle(client, alice, bank, "800")
    assert (
        refused.status_code == 400
        and "300" in refused.json()["detail"]
        and "say what the rest is" in refused.json()["detail"]
    )
    assert balance(client, bank["id"]) == 9500, "nothing was recorded"
    assert settle(client, alice, bank, "500", excess_as="gift").status_code == 400, "nothing is left over"
    assert settle(client, alice, bank, "800", excess_as="loan").status_code == 400, "the wrong way round"
    assert settle(client, alice, bank, "800", excess_as="gift", excess_category_id=None).status_code == 201


def test_the_rest_can_become_a_borrowing_an_advance_or_a_gift(client, bank, alice):
    lend(client, alice, bank, "500")
    got = settle(client, alice, bank, "800", excess_as="borrowing")
    assert got.status_code == 201, got.text
    body = got.json()
    assert float(body["excess"]) == 300 and body["excess_as"] == "borrowing" and body["excess_obligation_id"]
    assert balance(client, alice["receivable_account_id"]) == 0 and balance(client, alice["payable_account_id"]) == 300
    assert balance(client, bank["id"]) == 10300
    payable = client.get(f"/api/contacts/{alice['id']}/obligations", params={"direction": "payable"}).json()
    assert [(o["source_type"], float(o["outstanding_amount"])) for o in payable] == [("borrowing", 300.0)]
    gift = category(client, "Presents", kind="earning")
    ok = settle(client, alice, bank, "50", excess_as="gift", excess_category_id=gift["id"])
    assert ok.status_code == 201, (
        "nothing is owed to you any more, so all 50 is the rest: a gift under an earning category"
    )
    assert balance(client, bank["id"]) == 10350
    assert (
        settle(
            client, alice, bank, "5", excess_as="gift", excess_category_id=category(client, "Spend")["id"]
        ).status_code
        == 400
    )


def test_paying_back_what_you_owe(client, bank, alice):
    lend(client, alice, bank, "2000", direction="received", purpose="borrowing")
    assert balance(client, bank["id"]) == 12000
    made = settle(client, alice, bank, "500", direction="sent")
    assert made.status_code == 201, made.text
    assert balance(client, bank["id"]) == 11500 and balance(client, alice["payable_account_id"]) == 1500
    assert owed(client, alice, direction="payable") == [("borrowing", 1500.0, "partially_settled")]
    more = settle(client, alice, bank, "1600", direction="sent", excess_as="loan")
    assert more.status_code == 201 and float(more.json()["excess"]) == 100
    assert balance(client, alice["receivable_account_id"]) == 100 and balance(client, alice["payable_account_id"]) == 0


def test_a_receivable_is_never_settled_against_a_payable(client, bank, alice):
    lend(client, alice, bank, "500", direction="received", purpose="borrowing")
    refused = settle(client, alice, bank, "100")
    assert refused.status_code == 400 and "say what the rest is" in refused.json()["detail"], "nothing is owed to you"
    ids = [o["id"] for o in client.get(f"/api/contacts/{alice['id']}/obligations").json()]
    wrong_way = settle(
        client, alice, bank, "100", allocation_method="manual", allocations=[{"obligation_id": ids[0], "amount": "100"}]
    )
    assert wrong_way.status_code == 400 and "other way round" in wrong_way.json()["detail"]
    bob = client.post("/api/contacts/", json={"name": "Bob"}).json()
    lend(client, bob, bank, "50")
    others = settle(
        client, bob, bank, "50", allocation_method="manual", allocations=[{"obligation_id": ids[0], "amount": "50"}]
    )
    assert others.status_code == 400, "another contact's obligation"


def test_a_settled_obligation_cannot_be_settled_again(client, bank, alice):
    loan = lend(client, alice, bank, "500")
    assert settle(client, alice, bank, "500").status_code == 201
    again = settle(
        client,
        alice,
        bank,
        "500",
        allocation_method="manual",
        allocations=[{"obligation_id": loan["obligation_id"], "amount": "500"}],
    )
    assert again.status_code == 400 and "nothing is left" in again.json()["detail"]
    assert balance(client, alice["receivable_account_id"]) == 0


def test_the_preview_shows_the_allocation_and_saves_nothing(client, bank, alice, three):
    preview = client.post(
        f"/api/contacts/{alice['id']}/settlements/preview",
        json={"direction": "received", "amount": "1700", "account_id": bank["id"]},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert [float(a["amount"]) for a in body["allocations"]] == [500, 1000, 200]
    assert float(body["allocated"]) == 1700 and float(body["excess"]) == 0 and float(body["remaining"]) == 1800
    assert (
        balance(client, bank["id"]) == 6500 and len(client.get(f"/api/contacts/{alice['id']}/settlements").json()) == 0
    )


def test_reversing_a_settlement_makes_it_owed_again(client, bank, alice, three):
    made = settle(client, alice, bank, "1700").json()
    assert client.delete(f"/api/settlements/{made['id']}").status_code == 204
    assert [o[1] for o in owed(client, alice)] == [500.0, 1000.0, 2000.0]
    assert balance(client, bank["id"]) == 6500
    assert client.get(f"/api/settlements/{made['id']}").status_code == 404
    assert client.delete(f"/api/settlements/{made['id']}").status_code == 404
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_a_loan_cannot_be_reversed_while_something_is_settled_against_it(client, bank, alice):
    loan = lend(client, alice, bank, "500")
    paid = settle(client, alice, bank, "100").json()
    blocked = client.delete(f"/api/transfers/{loan['id']}")
    assert blocked.status_code == 409 and "settlement" in blocked.json()["detail"]
    assert client.delete(f"/api/settlements/{paid['id']}").status_code == 204
    assert client.delete(f"/api/transfers/{loan['id']}").status_code == 204


def test_what_a_settlement_left_owed_blocks_its_reversal_until_that_is_cleared(client, bank, alice):
    lend(client, alice, bank, "500")
    over = settle(client, alice, bank, "800", excess_as="borrowing").json()
    settle(client, alice, bank, "100", direction="sent")
    blocked = client.delete(f"/api/settlements/{over['id']}")
    assert blocked.status_code == 409


def test_an_entry_that_settled_something_is_not_edited_or_deleted_on_the_ordinary_screens(client, bank, alice):
    lend(client, alice, bank, "500")
    made = settle(client, alice, bank, "100").json()
    assert client.delete(f"/api/transactions/{made['id']}").status_code == 400
    assert client.patch(f"/api/transactions/{made['id']}", json={"payee": "x"}).status_code == 400


def test_a_retry_with_the_same_key_settles_once(client, bank, alice):
    lend(client, alice, bank, "500")
    url = f"/api/contacts/{alice['id']}/settlements"
    body = {"direction": "received", "amount": "200", "account_id": bank["id"], "date": "2026-10-05"}
    first = client.post(url, json=body, headers={"Idempotency-Key": "s1"})
    again = client.post(url, json=body, headers={"Idempotency-Key": "s1"})
    assert first.status_code == 201 and again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert owed(client, alice) == [("loan", 300.0, "partially_settled")]
    assert client.post(url, json={**body, "amount": "201"}, headers={"Idempotency-Key": "s1"}).status_code == 409


def test_two_settlements_of_the_same_remaining_balance(client, bank, alice):
    """The second one finds nothing left: the owed figures are read again each time, not trusted from before."""
    lend(client, alice, bank, "500")
    assert settle(client, alice, bank, "500").status_code == 201
    second = settle(client, alice, bank, "500")
    assert second.status_code == 400
    assert balance(client, alice["receivable_account_id"]) == 0 and balance(client, bank["id"]) == 10000


def test_unknown_archived_and_foreign_things(client, bank, alice, root_accounts):
    assert settle(client, {"id": MISSING}, bank, "5").status_code == 404
    lend(client, alice, bank, "50")
    assert settle(client, alice, {"id": alice["receivable_account_id"]}, "5").status_code == 400
    assert settle(client, alice, {"id": root_accounts["Income"]}, "5").status_code == 400
    assert settle(client, alice, bank, "0").status_code == 422
    bob = client.post("/api/contacts/", json={"name": "Bob"}).json()
    client.post(f"/api/contacts/{bob['id']}/archive")
    gone = settle(client, bob, bank, "5", excess_as="gift")
    assert gone.status_code == 400 and "archived" in gone.json()["detail"]
    assert client.get(f"/api/settlements/{MISSING}").status_code == 404


def test_paying_back_a_share_of_a_bill_a_friend_paid_counts_in_the_budget_then(client, bank, alice):
    food = category(client, "Dining")
    client.put(f"/api/budget/categories/{food['id']}", json={"amount": "1000"})
    made = client.post(
        "/api/shared-expenses/",
        params={"confirm": True},
        json={
            "description": "Dinner",
            "total_amount": "600",
            "category_id": food["id"],
            "participants": [{"is_self": True}, {"contact_id": alice["id"]}],
            "contributions": [{"contact_id": alice["id"], "amount": "600"}],
        },
    )
    assert made.status_code == 201, made.text
    line = lambda: next(l for l in client.get("/api/budget/").json()["lines"] if l["name"] == "Dining")
    assert float(line()["activity"]) == 0, "your bank did not move, so the budget has not seen it yet"
    settle(client, alice, bank, "300", direction="sent")
    assert float(line()["activity"]) == 300, "paid back: the spending reaches the budget"
    assert balance(client, bank["id"]) == 9700
    assert client.get("/api/budget/").json()["uncategorised"] == []


def test_paying_back_a_share_the_budget_already_saw_is_not_counted_twice(client, bank, alice):
    food = category(client, "Dining")
    made = client.post(
        "/api/shared-expenses/",
        params={"confirm": True},
        json={
            "description": "Dinner",
            "total_amount": "600",
            "category_id": food["id"],
            "participants": [{"is_self": True}, {"contact_id": alice["id"]}],
            "payments": [{"account_id": bank["id"], "amount": "400"}],
            "contributions": [{"contact_id": alice["id"], "amount": "200"}],
        },
    )
    assert made.status_code == 201, made.text
    assert balance(client, alice["receivable_account_id"]) == 100, "you paid 400 for a 300 share"
    activity = lambda: float(
        next(l for l in client.get("/api/budget/").json()["lines"] if l["name"] == "Dining")["activity"]
    )
    assert activity() == 300
    settle(client, alice, bank, "100")
    assert activity() == 300
