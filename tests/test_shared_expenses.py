"""Expenses shared with contacts: the shares, the ledger entry, who owes whom and what the budget sees."""

import pytest

from .books import category

MISSING = "00000000-0000-4000-8000-0000000000aa"


@pytest.fixture
def bank(client, root_accounts):
    return client.post(
        "/api/accounts/", json={"name": "HDFC", "parent_id": root_accounts["Assets"], "balance": "10000"}
    ).json()


@pytest.fixture
def dining(client):
    return category(client, "Dining")


@pytest.fixture
def people(client):
    return {name: client.post("/api/contacts/", json={"name": name}).json() for name in ("Alice", "Bob")}


def balance(client, account_id):
    return float(client.get(f"/api/accounts/{account_id}").json()["balance"])


def dinner(bank, dining, people, **extra):
    body = {
        "description": "Dinner",
        "total_amount": "1500.00",
        "category_id": dining["id"],
        "split_method": "equal",
        "participants": [
            {"is_self": True},
            {"contact_id": people["Alice"]["id"]},
            {"contact_id": people["Bob"]["id"]},
        ],
        "payments": [{"account_id": bank["id"], "amount": "1500.00"}],
    }
    body.update(extra)
    return body


def spent(client, name="Dining"):
    lines = client.get("/api/reports/breakdown").json()["lines"]
    return next((float(l["amount"]) for l in lines if l["account"] == name), 0.0)


def test_you_pay_for_everyone(client, bank, dining, people):
    made = client.post("/api/shared-expenses/", params={"confirm": True}, json=dinner(bank, dining, people))
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["status"] == "confirmed" and body["transaction_id"]
    assert [float(s["share_amount"]) for s in body["shares"]] == [500, 500, 500]
    assert balance(client, bank["id"]) == 8500
    assert balance(client, people["Alice"]["receivable_account_id"]) == 500
    assert balance(client, people["Bob"]["receivable_account_id"]) == 500
    assert spent(client) == 500, "only your share counts as spending"
    owed = {o["name"]: (o["direction"], float(o["amount"])) for o in body["owed"]}
    assert owed == {"Alice": ("receivable", 500), "Bob": ("receivable", 500)}
    entry = client.get(f"/api/transactions/{body['transaction_id']}").json()
    assert entry["payee"] == "Dinner" and len(entry["postings"]) == 4
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    alice = client.get(f"/api/contacts/{people['Alice']['id']}/obligations").json()
    assert [(o["source_type"], o["direction"], float(o["outstanding_amount"])) for o in alice] == [
        ("shared_expense", "receivable", 500)
    ]


def test_a_contact_pays_for_everyone_and_nothing_leaves_your_accounts(client, bank, dining, people):
    body = dinner(
        bank,
        dining,
        people,
        split_method="exact",
        participants=[
            {"is_self": True, "value": "500"},
            {"contact_id": people["Alice"]["id"], "value": "1000"},
        ],
        payments=[],
        contributions=[{"contact_id": people["Alice"]["id"], "amount": "1500"}],
    )
    made = client.post("/api/shared-expenses/", params={"confirm": True}, json=body)
    assert made.status_code == 201, made.text
    assert balance(client, bank["id"]) == 10000, "no fictional bank movement"
    assert balance(client, people["Alice"]["payable_account_id"]) == 500
    assert made.json()["owed"][0]["direction"] == "payable"
    entry = client.get(f"/api/transactions/{made.json()['transaction_id']}").json()
    assert len(entry["postings"]) == 2
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_mixed_contributions(client, bank, dining, people):
    body = dinner(
        bank,
        dining,
        people,
        total_amount="1500",
        participants=[{"is_self": True}, {"contact_id": people["Alice"]["id"]}],
        payments=[{"account_id": bank["id"], "amount": "1000"}],
        contributions=[{"contact_id": people["Alice"]["id"], "amount": "500"}],
    )
    made = client.post("/api/shared-expenses/", params={"confirm": True}, json=body)
    assert made.status_code == 201, made.text
    assert balance(client, bank["id"]) == 9000
    assert balance(client, people["Alice"]["receivable_account_id"]) == 250
    assert spent(client) == 750
    assert [(s["name"], float(s["net"])) for s in made.json()["shares"]] == [("You", 250.0), ("Alice", -250.0)]


def test_two_contacts_paid_more_and_less_each_settle_with_you(client, bank, dining, people):
    """Alice paid for Bob: nobody owes a third contact, so Bob owes you and you owe Alice."""
    body = dinner(
        bank,
        dining,
        people,
        payments=[],
        contributions=[{"contact_id": people["Alice"]["id"], "amount": "1500"}],
    )
    made = client.post("/api/shared-expenses/", params={"confirm": True}, json=body)
    assert made.status_code == 201, made.text
    assert balance(client, people["Alice"]["payable_account_id"]) == 1000
    assert balance(client, people["Bob"]["receivable_account_id"]) == 500
    assert spent(client) == 500
    assert client.get("/api/reports/trial-balance").json()["balanced"]


@pytest.mark.parametrize(
    ("method", "values", "expected"),
    [
        ("equal", [None, None, None], [500, 500, 500]),
        ("percentage", ["50", "30", "20"], [750, 450, 300]),
        ("shares", ["1", "2", "2"], [300, 600, 600]),
        ("exact", ["100", "400", "1000"], [100, 400, 1000]),
    ],
)
def test_every_way_of_splitting(client, bank, dining, people, method, values, expected):
    ids = [{"is_self": True}, {"contact_id": people["Alice"]["id"]}, {"contact_id": people["Bob"]["id"]}]
    participants = [{**p, "value": v} for p, v in zip(ids, values, strict=True)]
    made = client.post(
        "/api/shared-expenses/", json=dinner(bank, dining, people, split_method=method, participants=participants)
    )
    assert made.status_code == 201, made.text
    assert [float(s["share_amount"]) for s in made.json()["shares"]] == expected
    assert sum(float(s["share_amount"]) for s in made.json()["shares"]) == 1500


def test_rounding_gives_every_unit_to_someone(client, bank, dining, people):
    made = client.post(
        "/api/shared-expenses/",
        json=dinner(bank, dining, people, total_amount="100", payments=[{"account_id": bank["id"], "amount": "100"}]),
    )
    assert [float(s["share_amount"]) for s in made.json()["shares"]] == [33.34, 33.33, 33.33]
    client.post(f"/api/shared-expenses/{made.json()['id']}/confirm")
    assert balance(client, people["Alice"]["receivable_account_id"]) == 33.33
    assert spent(client) == 33.34


def test_a_draft_changes_nothing_until_confirmed(client, bank, dining, people):
    draft = client.post("/api/shared-expenses/", json=dinner(bank, dining, people)).json()
    assert draft["status"] == "draft" and draft["transaction_id"] is None and draft["lines"]
    assert balance(client, bank["id"]) == 10000 and spent(client) == 0
    assert [e["id"] for e in client.get("/api/shared-expenses/", params={"status": "draft"}).json()] == [draft["id"]]
    assert client.get("/api/shared-expenses/", params={"status": "confirmed"}).json() == []
    changed = client.patch(
        f"/api/shared-expenses/{draft['id']}",
        json={
            "total_amount": "900",
            "description": "Lunch",
            "payments": [{"account_id": bank["id"], "amount": "900"}],
        },
    )
    assert changed.status_code == 200, changed.text
    assert [float(s["share_amount"]) for s in changed.json()["shares"]] == [300, 300, 300]
    assert changed.json()["description"] == "Lunch"
    done = client.post(f"/api/shared-expenses/{draft['id']}/confirm")
    assert done.status_code == 200 and done.json()["status"] == "confirmed"
    assert balance(client, bank["id"]) == 9100 and spent(client) == 300


def test_a_confirmed_expense_is_not_edited_or_confirmed_again(client, bank, dining, people):
    made = client.post("/api/shared-expenses/", params={"confirm": True}, json=dinner(bank, dining, people)).json()
    assert client.post(f"/api/shared-expenses/{made['id']}/confirm").status_code == 409
    assert client.patch(f"/api/shared-expenses/{made['id']}", json={"description": "x"}).status_code == 409
    assert client.patch(f"/api/transactions/{made['transaction_id']}", json={"payee": "x"}).status_code == 400
    assert client.delete(f"/api/transactions/{made['transaction_id']}").status_code == 400


def test_an_expense_that_is_not_fully_paid_for_stays_a_draft(client, bank, dining, people):
    part = dinner(bank, dining, people, payments=[{"account_id": bank["id"], "amount": "1000"}])
    draft = client.post("/api/shared-expenses/", json=part).json()
    assert float(draft["unfunded"]) == 500 and draft["lines"] == []
    refused = client.post(f"/api/shared-expenses/{draft['id']}/confirm")
    assert refused.status_code == 400 and "not the total" in refused.json()["detail"]
    assert client.post("/api/shared-expenses/", params={"confirm": True}, json=part).status_code == 400
    assert client.get("/api/shared-expenses/").json()[0]["id"] == draft["id"], "the failed one-step save left nothing"
    assert len(client.get("/api/shared-expenses/").json()) == 1
    over = dinner(bank, dining, people, payments=[{"account_id": bank["id"], "amount": "1600"}])
    assert client.post("/api/shared-expenses/", params={"confirm": True}, json=over).status_code == 400


def test_the_preview_saves_nothing(client, bank, dining, people):
    preview = client.post("/api/shared-expenses/preview", json=dinner(bank, dining, people))
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert float(body["user_share"]) == 500 and float(body["user_paid"]) == 1500 and len(body["lines"]) == 4
    assert {o["name"] for o in body["owed"]} == {"Alice", "Bob"}
    assert client.get("/api/shared-expenses/").json() == []
    assert balance(client, bank["id"]) == 10000


def test_cancelling_a_draft_and_reversing_a_confirmed_expense(client, bank, dining, people):
    draft = client.post("/api/shared-expenses/", json=dinner(bank, dining, people)).json()
    assert client.post(f"/api/shared-expenses/{draft['id']}/cancel").status_code == 204
    assert client.get(f"/api/shared-expenses/{draft['id']}").status_code == 404
    made = client.post("/api/shared-expenses/", params={"confirm": True}, json=dinner(bank, dining, people)).json()
    assert client.post(f"/api/shared-expenses/{made['id']}/cancel").status_code == 204
    assert balance(client, bank["id"]) == 10000 and spent(client) == 0
    assert balance(client, people["Alice"]["receivable_account_id"]) == 0
    assert client.get(f"/api/contacts/{people['Alice']['id']}/obligations").json() == []
    assert client.get(f"/api/transactions/{made['transaction_id']}").status_code == 404
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    assert client.post(f"/api/shared-expenses/{MISSING}/cancel").status_code == 404


def test_the_rules_of_who_shares_and_who_pays(client, bank, dining, people):
    def attempt(**extra):
        return client.post("/api/shared-expenses/", json=dinner(bank, dining, people, **extra))

    alice, bob = people["Alice"]["id"], people["Bob"]["id"]
    assert attempt(participants=[{"is_self": True}]).status_code == 422, "at least two"
    assert attempt(participants=[{"contact_id": alice}, {"contact_id": bob}]).status_code == 400, "you must be in it"
    assert attempt(participants=[{"is_self": True}, {"contact_id": alice}, {"contact_id": alice}]).status_code == 400
    assert attempt(participants=[{"is_self": True}, {"is_self": True}, {"contact_id": alice}]).status_code == 400
    assert attempt(participants=[{"is_self": True, "contact_id": alice}, {"contact_id": bob}]).status_code == 422
    assert attempt(participants=[{"is_self": True}, {"contact_id": MISSING}]).status_code == 404
    assert attempt(total_amount="0").status_code == 422
    assert attempt(total_amount="10.001", payments=[]).status_code == 400
    assert attempt(contributions=[{"contact_id": MISSING, "amount": "5"}]).status_code == 400
    carol = client.post("/api/contacts/", json={"name": "Carol"}).json()
    assert attempt(contributions=[{"contact_id": carol["id"], "amount": "5"}]).status_code == 400, "paid but not in it"
    assert attempt(payments=[{"account_id": bank["id"], "amount": "5"}] * 2).status_code == 400
    assert (
        attempt(payments=[{"account_id": people["Alice"]["receivable_account_id"], "amount": "1500"}]).status_code
        == 400
    )
    assert attempt(split_method="percentage").status_code == 400, "no values"
    assert attempt(description="  ").status_code == 422
    assert client.get("/api/shared-expenses/").json() == []


def test_an_archived_contact_cannot_be_added(client, bank, dining, people):
    client.post(f"/api/contacts/{people['Bob']['id']}/archive")
    refused = client.post("/api/shared-expenses/", json=dinner(bank, dining, people))
    assert refused.status_code == 400 and "archived" in refused.json()["detail"]


def test_a_contact_in_a_draft_cannot_be_hard_deleted(client, bank, dining, people):
    client.post("/api/shared-expenses/", json=dinner(bank, dining, people))
    gone = client.delete(f"/api/contacts/{people['Alice']['id']}")
    assert gone.status_code == 200 and gone.json()["outcome"] == "archived"


def test_a_retry_with_the_same_key_records_it_once(client, bank, dining, people):
    body = dinner(bank, dining, people)
    first = client.post("/api/shared-expenses/", params={"confirm": True}, json=body, headers={"Idempotency-Key": "k1"})
    again = client.post("/api/shared-expenses/", params={"confirm": True}, json=body, headers={"Idempotency-Key": "k1"})
    assert first.status_code == 201 and again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert balance(client, bank["id"]) == 8500 and len(client.get("/api/shared-expenses/").json()) == 1
    other = client.post(
        "/api/shared-expenses/",
        params={"confirm": True},
        json={**body, "description": "Other"},
        headers={"Idempotency-Key": "k1"},
    )
    assert other.status_code == 409
    draft = client.post("/api/shared-expenses/", json=body).json()
    confirmed = client.post(f"/api/shared-expenses/{draft['id']}/confirm", headers={"Idempotency-Key": "k2"})
    repeated = client.post(f"/api/shared-expenses/{draft['id']}/confirm", headers={"Idempotency-Key": "k2"})
    assert confirmed.status_code == 200 and repeated.status_code == 200 and balance(client, bank["id"]) == 7000
    wrong = client.post(f"/api/shared-expenses/{first.json()['id']}/confirm", headers={"Idempotency-Key": "k2"})
    assert wrong.status_code == 409


def test_a_shared_expense_with_nothing_spent_or_owed_is_refused(client, bank, dining, people):
    body = dinner(
        bank,
        dining,
        people,
        total_amount="100",
        split_method="exact",
        participants=[{"is_self": True, "value": "0"}, {"contact_id": people["Alice"]["id"], "value": "100"}],
        payments=[],
        contributions=[{"contact_id": people["Alice"]["id"], "amount": "100"}],
    )
    refused = client.post("/api/shared-expenses/", params={"confirm": True}, json=body)
    assert refused.status_code == 400 and "no entry to record" in refused.json()["detail"]


def test_a_card_can_pay_and_the_budget_sees_only_your_share(client, bank, dining, people, root_accounts):
    card = client.post(
        "/api/accounts/", json={"name": "Visa", "parent_id": root_accounts["Liabilities"], "on_budget": True}
    ).json()
    client.put(f"/api/budget/categories/{dining['id']}", json={"amount": "1000"})
    body = dinner(bank, dining, people, payments=[{"account_id": card["id"], "amount": "1500"}])
    assert client.post("/api/shared-expenses/", params={"confirm": True}, json=body).status_code == 201
    view = client.get("/api/budget/").json()
    line = next(l for l in view["lines"] if l["name"] == "Dining")
    assert float(line["activity"]) == 500 and float(line["available"]) == 500
    assert view["uncategorised"] == []
    assert balance(client, card["id"]) == 1500, "the card owes the whole bill"


def test_the_category_must_be_an_open_spending_category(client, bank, dining, people):
    pay = category(client, "Pay", kind="earning")
    refused = client.post("/api/shared-expenses/", json=dinner(bank, dining, people, category_id=pay["id"]))
    assert refused.status_code == 400 and "spending categories" in refused.json()["detail"]
    assert (
        client.post("/api/shared-expenses/", json=dinner(bank, dining, people, category_id=MISSING)).status_code == 400
    )
    client.post(f"/api/categories/{dining['id']}/close")
    closed = client.post("/api/shared-expenses/", json=dinner(bank, dining, people))
    assert closed.status_code == 400 and "closed" in closed.json()["detail"]
    no_category = client.post(
        "/api/shared-expenses/", params={"confirm": True}, json=dinner(bank, dining, people, category_id=None)
    )
    assert no_category.status_code == 201
    assert spent(client, "Uncategorised") == 500
