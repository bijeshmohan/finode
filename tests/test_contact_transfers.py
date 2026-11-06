"""Loans, borrowings, advances and gifts with a contact: the entries, what is left owed, the budget and the guards."""

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


def send(client, contact, bank, direction="sent", purpose="loan", amount="5000", **extra):
    return client.post(
        f"/api/contacts/{contact['id']}/transfers",
        json={"direction": direction, "purpose": purpose, "amount": amount, "account_id": bank["id"], **extra},
    )


def balance(client, account_id):
    return float(client.get(f"/api/accounts/{account_id}").json()["balance"])


def test_lending_debits_due_from_and_leaves_a_receivable(client, bank, alice):
    made = send(client, alice, bank, description="Personal loan to Alice")
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["purpose"] == "loan" and body["direction"] == "sent" and float(body["amount"]) == 5000
    assert body["account_id"] == bank["id"] and body["obligation_id"]
    assert balance(client, bank["id"]) == 5000 and balance(client, alice["receivable_account_id"]) == 5000
    assert balance(client, alice["payable_account_id"]) == 0
    owed = client.get(f"/api/contacts/{alice['id']}/obligations").json()
    assert len(owed) == 1 and owed[0]["direction"] == "receivable" and owed[0]["source_type"] == "loan"
    assert float(owed[0]["outstanding_amount"]) == 5000 and owed[0]["status"] == "open"
    assert owed[0]["description"] == "Personal loan to Alice"
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_borrowing_credits_due_to_and_leaves_a_payable(client, bank, alice):
    made = send(client, alice, bank, direction="received", purpose="borrowing", amount="2000")
    assert made.status_code == 201, made.text
    assert balance(client, bank["id"]) == 12000 and balance(client, alice["payable_account_id"]) == 2000
    owed = client.get(f"/api/contacts/{alice['id']}/obligations", params={"direction": "payable"}).json()
    assert [o["source_type"] for o in owed] == ["borrowing"]
    assert client.get(f"/api/contacts/{alice['id']}/obligations", params={"direction": "receivable"}).json() == []


def test_an_advance_goes_either_way(client, bank, alice):
    sent = send(client, alice, bank, purpose="advance", amount="100").json()
    got = send(client, alice, bank, direction="received", purpose="advance", amount="40").json()
    assert balance(client, alice["receivable_account_id"]) == 100 and balance(client, alice["payable_account_id"]) == 40
    assert sent["obligation_id"] and got["obligation_id"]
    kinds = {o["direction"]: o["source_type"] for o in client.get(f"/api/contacts/{alice['id']}/obligations").json()}
    assert kinds == {"receivable": "advance", "payable": "advance"}


def test_a_gift_is_spending_or_income_and_owes_nothing(client, bank, alice):
    treats = category(client, "Treats")
    sent = send(client, alice, bank, purpose="gift", amount="1000", category_id=treats["id"])
    assert sent.status_code == 201 and sent.json()["obligation_id"] is None
    assert balance(client, bank["id"]) == 9000
    assert balance(client, alice["receivable_account_id"]) == 0
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json() == []
    month = client.get("/api/reports/breakdown").json()
    assert {l["account"]: float(l["amount"]) for l in month["lines"]}["Treats"] == 1000
    salary = category(client, "Presents", kind="earning")
    got = send(client, alice, bank, direction="received", purpose="gift", amount="200", category_id=salary["id"])
    assert got.status_code == 201 and balance(client, bank["id"]) == 9200


def test_a_gift_without_a_category_is_uncategorised(client, bank, alice):
    assert send(client, alice, bank, purpose="gift", amount="50").status_code == 201
    names = [l["account"] for l in client.get("/api/reports/breakdown").json()["lines"]]
    assert names == ["Uncategorised"]


def test_the_purpose_must_fit_the_direction_and_the_category(client, bank, alice):
    assert send(client, alice, bank, direction="sent", purpose="borrowing").status_code == 400
    assert send(client, alice, bank, direction="received", purpose="loan").status_code == 400
    treats = category(client, "Treats")
    refused = send(client, alice, bank, purpose="loan", category_id=treats["id"])
    assert refused.status_code == 400 and "only a gift" in refused.json()["detail"]
    assert send(client, alice, bank, amount="0").status_code == 422
    assert send(client, alice, bank, purpose="other").status_code == 422


def test_the_account_must_be_one_of_yours(client, bank, alice, root_accounts):
    assert send(client, alice, {"id": alice["receivable_account_id"]}).status_code == 400
    assert send(client, alice, {"id": root_accounts["Expenses"]}).status_code == 400
    assert send(client, alice, {"id": MISSING}).status_code == 400
    assert client.get(f"/api/contacts/{alice['id']}/transfers").json() == []


def test_an_archived_or_unknown_contact_takes_no_transfer(client, bank, alice):
    assert client.post(f"/api/contacts/{alice['id']}/archive").status_code == 200
    refused = send(client, alice, bank)
    assert refused.status_code == 400 and "archived" in refused.json()["detail"]
    assert send(client, {"id": MISSING}, bank).status_code == 404


def test_lending_moves_ready_to_assign_but_no_category(client, bank, alice):
    before = float(client.get("/api/budget/").json()["ready_to_assign"])
    send(client, alice, bank)
    after = client.get("/api/budget/").json()
    assert float(after["ready_to_assign"]) == before - 5000, "the money left the budget"
    assert after["uncategorised"] == [], "a loan is not a payment waiting for a category"
    assert all(float(l["activity"]) == 0 for l in after["lines"])
    todo = client.get("/api/todo/").json()
    assert todo["uncategorised"] == [] and todo["left_out_accounts"] == []


def test_a_contacts_accounts_cannot_be_used_on_the_ordinary_screens(client, bank, alice):
    lines = [
        {"account_id": alice["receivable_account_id"], "side": "debit", "amount": "10"},
        {"account_id": bank["id"], "side": "credit", "amount": "10"},
    ]
    refused = client.post("/api/transactions/", json={"postings": lines})
    assert refused.status_code == 400 and "belongs to a contact" in refused.json()["detail"]
    assert client.post("/api/transactions/batch", json={"transactions": [{"postings": lines}]}).status_code in (
        400,
        422,
    )
    rule = client.post(
        "/api/recurring/",
        json={
            "from_account_id": bank["id"],
            "to_account_id": alice["receivable_account_id"],
            "amount": "5",
            "frequency": "monthly",
            "start_date": "2999-01-01",
        },
    )
    assert rule.status_code == 400


def test_an_entry_a_contact_owns_is_not_edited_or_deleted_on_the_ordinary_screens(client, bank, alice):
    loan = send(client, alice, bank).json()
    assert client.patch(f"/api/transactions/{loan['id']}", json={"payee": "x"}).status_code == 400
    refused = client.delete(f"/api/transactions/{loan['id']}")
    assert refused.status_code == 400 and "belongs to a contact" in refused.json()["detail"]
    gift = send(client, alice, bank, purpose="gift", amount="5").json()
    assert client.delete(f"/api/transactions/{gift['id']}").status_code == 400, "gifts too: they are in the activity"
    assert balance(client, alice["receivable_account_id"]) == 5000


def test_reversing_a_transfer_takes_everything_back(client, bank, alice):
    loan = send(client, alice, bank).json()
    assert client.get(f"/api/transfers/{loan['id']}").json()["id"] == loan["id"]
    assert [t["id"] for t in client.get(f"/api/contacts/{alice['id']}/transfers").json()] == [loan["id"]]
    assert client.delete(f"/api/transfers/{loan['id']}").status_code == 204
    assert balance(client, bank["id"]) == 10000 and balance(client, alice["receivable_account_id"]) == 0
    assert client.get(f"/api/contacts/{alice['id']}/obligations").json() == []
    assert client.get(f"/api/transfers/{loan['id']}").status_code == 404
    assert client.delete(f"/api/transfers/{loan['id']}").status_code == 404
    assert client.get(f"/api/transactions/{loan['id']}").status_code == 404
    assert client.get("/api/reports/trial-balance").json()["balanced"]


def test_a_retry_with_the_same_key_returns_the_first_result(client, bank, alice):
    body = {"direction": "sent", "purpose": "loan", "amount": "500", "account_id": bank["id"], "date": "2026-10-01"}
    url = f"/api/contacts/{alice['id']}/transfers"
    first = client.post(url, json=body, headers={"Idempotency-Key": "abc"})
    again = client.post(url, json=body, headers={"Idempotency-Key": "abc"})
    assert first.status_code == 201 and again.status_code == 201 and again.json()["id"] == first.json()["id"]
    assert balance(client, alice["receivable_account_id"]) == 500, "recorded once"
    different = client.post(url, json={**body, "amount": "501"}, headers={"Idempotency-Key": "abc"})
    assert different.status_code == 409
    other = client.post(url, json=body, headers={"Idempotency-Key": "xyz"})
    assert other.status_code == 201 and other.json()["id"] != first.json()["id"]
    assert client.delete(f"/api/transfers/{first.json()['id']}").status_code == 204
    again_after = client.post(url, json=body, headers={"Idempotency-Key": "abc"})
    assert again_after.status_code == 201 and again_after.json()["id"] != first.json()["id"], "the key went with it"


def test_obligations_of_an_unknown_contact(client):
    assert client.get(f"/api/contacts/{MISSING}/obligations").status_code == 404
    assert client.get(f"/api/contacts/{MISSING}/transfers").status_code == 404
