"""/api/entries: what the finode app's Add screen saves. It records exactly what the web form records."""

from decimal import Decimal

from .books import category, post_account
from .svc import services
from .test_isolation import B_USER, signed_in_as


def made(client, root_accounts):
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1000"}).json()
    food = category(client, "Food")
    ada = client.post("/api/contacts/", json={"name": "Ada"}).json()
    return bank, food, ada


def entry(bank, to, amount="30", **extra):
    return {
        "kind": "expense",
        "rows": [
            {"choice": bank["id"], "side": "credit", "amount": amount},
            {"choice": to["id"], "side": "debit", "amount": amount},
        ],
        **extra,
    }


def lines(client, transaction_id):
    found = client.get(f"/api/transactions/{transaction_id}").json()
    return sorted((p["account_id"], p["side"], Decimal(p["amount"]), p["category_id"]) for p in found["postings"])


def test_an_entry_on_a_category_posts_as_the_web_form_does(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    saved = client.post("/api/entries", json=entry(bank, food, payee="Swiggy"))
    assert saved.status_code == 201, saved.text
    assert saved.json()["recorded"] == "transaction"
    web = client.post(
        "/transactions/split",
        data={
            "account": [bank["id"], food["id"]],
            "side": ["credit", "debit"],
            "amount": ["30", "30"],
            "kind": "expense",
            "payee": "Swiggy",
        },
    )
    assert web.status_code == 200, web.text
    web_id = next(
        t["id"]
        for t in client.get("/api/transactions/").json()
        if t["payee"] == "Swiggy" and t["id"] != saved.json()["transaction_id"]
    )
    assert lines(client, saved.json()["transaction_id"]) == lines(client, web_id)


def test_a_transfer_to_a_person_is_a_loan(client, root_accounts):
    bank, _, ada = made(client, root_accounts)
    saved = client.post("/api/entries", json={**entry(bank, ada, "200"), "kind": "transfer"})
    assert saved.status_code == 201 and saved.json()["recorded"] == "transfer"
    assert client.get(f"/api/contacts/{ada['id']}").json()["receivable"] == "200.00"


def test_editing_an_entry(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    saved = client.post("/api/entries", json=entry(bank, food)).json()
    changed = client.put(f"/api/entries/{saved['transaction_id']}", json=entry(bank, food, "45", payee="Cafe"))
    assert changed.status_code == 200, changed.text
    found = client.get(f"/api/transactions/{saved['transaction_id']}").json()
    assert found["payee"] == "Cafe" and {p["amount"] for p in found["postings"]} == {"45.00"}


def test_refusals_say_why(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    body = entry(bank, food)
    body["rows"][1]["amount"] = "20"
    refused = client.post("/api/entries", json=body)
    assert refused.status_code == 400 and refused.json()["detail"]


def test_another_persons_entry_is_not_found(client, root_accounts):
    bank, food, _ = made(client, root_accounts)
    saved = client.post("/api/entries", json=entry(bank, food)).json()
    with signed_in_as(B_USER):
        assert client.put(f"/api/entries/{saved['transaction_id']}", json=entry(bank, food)).status_code == 404


def test_the_books_stay_balanced(client, session, root_accounts):
    bank, food, ada = made(client, root_accounts)
    client.post("/api/entries", json=entry(bank, food))
    client.post("/api/entries", json={**entry(bank, ada, "50"), "kind": "transfer"})
    assert services(session).reports.trial_balance().balanced
