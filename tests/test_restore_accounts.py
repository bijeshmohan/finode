"""Bringing back deleted accounts (an unused one is removed for good but leaves a record to restore it from) and closed
categories (one with a history is closed when deleted, and listed)."""

import pytest

from app.clock import local_today

from .books import post_account

THIS_MONTH = local_today().replace(day=1)


@pytest.fixture
def books(client, root_accounts):
    def make(name, parent, **extra):
        r = post_account(client, {"name": name, "parent_id": parent, **extra})
        assert r.status_code == 201, r.text
        return r.json()["aid"]

    food = make("Food", root_accounts["Expenses"])
    return {
        "roots": root_accounts,
        "food": food,
        "snacks": make("Snacks", food),
        "bank": make("Bank", root_accounts["Assets"], balance="5000"),
        "make": make,
    }


def deleted(svc):
    return svc.accounts.restorable()


def restore(client, did):
    """Press Restore on the Recently deleted page."""
    return client.post(f"/accounts/deleted/{did}/restore")


def came_back(response) -> bool:
    return response.status_code == 200 and response.headers.get("HX-Redirect", "").startswith("/accounts/")


def test_a_deleted_account_with_a_budget_flag_comes_back_with_it(client, books, svc):
    wallet = books["make"]("Wallet", books["roots"]["Assets"], on_budget=False)
    client.delete(f"/api/accounts/{wallet}")
    [gone] = deleted(svc)
    restore(client, gone["did"])
    assert client.get(f"/api/accounts/{wallet}").json()["on_budget"] is False


def test_it_cannot_come_back_twice_or_into_a_missing_parent(client, books, svc):
    banks = books["make"]("Banks", books["roots"]["Assets"])
    wallet = books["make"]("Wallet", banks)
    client.delete(f"/api/accounts/{wallet}")
    [gone] = deleted(svc)
    assert came_back(restore(client, gone["did"]))
    again = restore(client, gone["did"])
    assert again.status_code == 400 and "already back" in again.text
    client.delete(f"/api/accounts/{wallet}")
    client.delete(f"/api/accounts/{banks}")  # now the parent goes too
    row = next(d for d in deleted(svc) if d["name"] == "Wallet")
    refused = restore(client, row["did"])
    assert refused.status_code == 400 and "no longer exists" in refused.text
    assert restore(client, "00000000-0000-4000-8000-000000000000").status_code == 404


def test_a_name_that_was_taken_since_blocks_the_restore(client, books, svc):
    wallet = books["make"]("Wallet", books["roots"]["Assets"])
    client.delete(f"/api/accounts/{wallet}")
    books["make"]("Wallet", books["roots"]["Assets"])
    [gone] = deleted(svc)
    refused = restore(client, gone["did"])
    assert refused.status_code == 400 and "already has" in refused.text


def test_the_categories_page_lists_closed_ones_and_restores_them(client, books):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": books["snacks"], "side": "debit", "amount": "10"},
                {"account": books["bank"], "side": "credit", "amount": "10"},
            ]
        },
    )
    used = client.post(f"/categories/{books['snacks']}/delete")  # it has an entry: closed, not removed
    assert used.status_code == 200
    page = client.get("/categories/deleted").text
    assert "Snacks" in page and "closed" in page
    assert client.post(f"/categories/{books['snacks']}/reopen").status_code == 200
    assert "Nothing deleted" in client.get("/categories/deleted").text


def test_accounts_and_categories_have_their_own_page(client, books):
    wallet = books["make"]("Wallet", books["roots"]["Assets"], on_budget=False)
    client.delete(f"/api/accounts/{wallet}")
    assert "Wallet" in client.get("/accounts/deleted").text and "Wallet" not in client.get("/categories/deleted").text
    assert 'href="/accounts/deleted"' in client.get("/settings").text, "Recently deleted is a row in Settings"
    assert "/deleted" not in client.get("/accounts").text and "/deleted" not in client.get("/categories").text, (
        "no bin in the page heads"
    )
    assert (
        'href="/settings"' in client.get("/accounts/deleted").text
        and 'href="/settings"' in client.get("/categories/deleted").text
    )
    for place in ("transactions", "accounts", "categories"):
        assert 'href="/transactions/deleted"' in client.get(f"/{place}/deleted").text, (
            "the three pages link to each other"
        )
