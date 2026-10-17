"""Bringing back deleted accounts and categories: an unused one is removed for good but leaves a record to restore
it from; one with a history is closed, and listed too."""

from datetime import date, timedelta

import pytest

from app.clock import local_today

THIS_MONTH = local_today().replace(day=1)


@pytest.fixture
def books(client, root_accounts):
    def make(name, parent, **extra):
        r = client.post("/api/accounts/", json={"name": name, "parent_id": parent, **extra})
        assert r.status_code == 201, r.text
        return r.json()["aid"]

    food = make("Food", root_accounts["Expenses"])
    return {"roots": root_accounts, "food": food, "snacks": make("Snacks", food), "bank": make("Bank", root_accounts["Assets"], balance="5000"),
            "make": make}


def deleted(client):
    return client.get("/api/accounts/deleted").json()


def test_deleting_an_unused_category_leaves_a_record_and_restoring_brings_it_back_whole(client, books):
    snacks = books["snacks"]
    client.patch(f"/api/accounts/{snacks}", json={"details": "treats"})
    client.put(f"/api/budget/categories/{snacks}", json={"month": THIS_MONTH.isoformat(), "amount": "250"})
    client.put(f"/api/budget/categories/{snacks}/target", json={"kind": "monthly", "amount": "300"})
    loan = books["make"]("Bike loan", books["roots"]["Liabilities"], on_budget=False)
    client.patch(f"/api/accounts/{loan}", json={"payment_category_id": snacks})
    assert client.delete(f"/api/accounts/{snacks}").status_code == 204
    assert client.get(f"/api/accounts/{snacks}").status_code == 404
    [gone] = deleted(client)
    assert gone["name"] == "Snacks" and gone["path"] == "Expenses:Food:Snacks" and gone["root"] == "Expenses"
    assert client.get(f"/api/accounts/{loan}").json()["payment_category_id"] is None, "the delete cleared the link"
    back = client.post(f"/api/accounts/deleted/{gone['did']}/restore")
    assert back.status_code == 201
    restored = client.get(f"/api/accounts/{snacks}").json()
    assert restored["name"] == "Snacks" and restored["parent_id"] == books["food"] and restored["details"] == "treats"
    budget = client.get(f"/api/budget/?month={THIS_MONTH.isoformat()}").json()
    line = next(l for l in budget["lines"] if l["name"] == "Snacks")
    assert line["assigned"] == "250.00" and line["target"]["amount"] == "300.00"
    assert client.get(f"/api/accounts/{loan}").json()["payment_category_id"] == snacks, "the payment link is back"
    assert deleted(client) == [], "what is back leaves the list"


def test_a_deleted_account_with_a_budget_flag_comes_back_with_it(client, books):
    wallet = books["make"]("Wallet", books["roots"]["Assets"], on_budget=False)
    client.delete(f"/api/accounts/{wallet}")
    [gone] = deleted(client)
    client.post(f"/api/accounts/deleted/{gone['did']}/restore")
    assert client.get(f"/api/accounts/{wallet}").json()["on_budget"] is False


def test_it_cannot_come_back_twice_or_into_a_missing_parent(client, books):
    snacks = books["snacks"]
    client.delete(f"/api/accounts/{snacks}")
    [gone] = deleted(client)
    assert client.post(f"/api/accounts/deleted/{gone['did']}/restore").status_code == 201
    again = client.post(f"/api/accounts/deleted/{gone['did']}/restore")
    assert again.status_code == 400 and "already back" in again.json()["detail"]
    client.delete(f"/api/accounts/{snacks}")
    client.delete(f"/api/accounts/{books['food']}")  # now the parent goes too
    snack_row = next(d for d in deleted(client) if d["name"] == "Snacks")
    refused = client.post(f"/api/accounts/deleted/{snack_row['did']}/restore")
    assert refused.status_code == 400 and "no longer exists" in refused.json()["detail"]
    assert client.post("/api/accounts/deleted/00000000-0000-4000-8000-000000000000/restore").status_code == 404


def test_a_name_that_was_taken_since_blocks_the_restore(client, books):
    client.delete(f"/api/accounts/{books['snacks']}")
    books["make"]("Snacks", books["food"])
    [gone] = deleted(client)
    refused = client.post(f"/api/accounts/deleted/{gone['did']}/restore")
    assert refused.status_code == 400 and "already has" in refused.json()["detail"]


def test_the_pages_list_closed_and_deleted_and_restore_both(client, books):
    # a category with entries is closed when deleted; an unused one is removed
    client.post("/api/transactions/", json={"postings": [
        {"account": books["snacks"], "side": "debit", "amount": "10"}, {"account": books["bank"], "side": "credit", "amount": "10"}]})
    used = client.post(f"/accounts/{books['snacks']}/delete")
    assert used.status_code == 200
    spare = books["make"]("Spare", books["food"])
    client.post(f"/accounts/{spare}/delete")
    page = client.get("/categories/deleted").text
    assert "Snacks" in page and "closed" in page and "Spare" in page and "deleted" in page
    assert f'hx-post="/accounts/{books["snacks"]}/reopen"' in page and "/accounts/deleted/" in page
    [gone] = deleted(client)
    done = client.post(f"/accounts/deleted/{gone['did']}/restore")
    assert done.status_code == 200 and done.headers["HX-Redirect"] == f"/accounts/{spare}"
    assert client.post(f"/accounts/{books['snacks']}/reopen").status_code == 200
    assert "Nothing deleted" in client.get("/categories/deleted").text


def test_accounts_and_categories_have_their_own_page(client, books):
    wallet = books["make"]("Wallet", books["roots"]["Assets"], on_budget=False)
    client.delete(f"/api/accounts/{wallet}")
    assert "Wallet" in client.get("/accounts/deleted").text and "Wallet" not in client.get("/categories/deleted").text
    assert 'href="/accounts/deleted"' in client.get("/accounts").text and 'href="/categories/deleted"' in client.get("/categories").text
    for place in ("transactions", "accounts", "categories"):
        assert 'href="/transactions/deleted"' in client.get(f"/{place}/deleted").text, "the three pages link to each other"

