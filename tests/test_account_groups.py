"""Groups the person makes: a shelf for accounts that can stand empty, holds money owned or owed, and says whether the
accounts made in it start in the budget."""

import re

import pytest

from app.services import account as account_service

from .books import post_account
from .conftest import TEST_USER_ID
from .test_backup import OTHER, as_user, restore_as_other


@pytest.fixture(autouse=True)
def new_person(monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)


def make_group(client, name="Family", root="Assets", budget=True):
    return client.post("/api/accounts/groups", json={"name": name, "root": root, "new_accounts_in_budget": budget})


def in_group(client, group, name, **extra):
    return post_account(client, {"name": name, "parent_id": group["id"], **extra})


def test_a_group_is_made_empty_under_the_type_it_holds(client, root_accounts):
    made = make_group(client)
    assert made.status_code == 201, made.text
    group = made.json()
    assert group["parent_id"] == root_accounts["Assets"] and group["new_accounts_in_budget"] is True
    assert group["system_key"] is None and group["balance"] == "0.00"
    owed = make_group(client, "Dues", "Liabilities", budget=False).json()
    assert owed["parent_id"] == root_accounts["Liabilities"] and owed["new_accounts_in_budget"] is False


def test_an_account_made_in_a_group_starts_as_the_group_says_unless_told(client):
    yes, no = make_group(client, "In", budget=True).json(), make_group(client, "Out", budget=False).json()
    assert in_group(client, yes, "A").json()["on_budget"] is True
    assert in_group(client, no, "B").json()["on_budget"] is False
    assert in_group(client, no, "C", on_budget=True).json()["on_budget"] is True
    assert in_group(client, yes, "D", on_budget=False).json()["on_budget"] is False


def test_changing_the_groups_choice_leaves_its_accounts_alone(client):
    group = make_group(client, budget=True).json()
    first = in_group(client, group, "First").json()
    changed = client.patch(f"/api/accounts/{group['id']}", json={"new_accounts_in_budget": False})
    assert changed.status_code == 200 and changed.json()["new_accounts_in_budget"] is False
    assert client.get(f"/api/accounts/{first['id']}").json()["on_budget"] is True
    assert in_group(client, group, "Second").json()["on_budget"] is False


def test_only_a_group_has_the_choice_and_it_cannot_be_cleared(client, root_accounts):
    group = make_group(client).json()
    plain = post_account(client, {"name": "Plain", "parent_id": root_accounts["Assets"]}).json()
    assert client.patch(f"/api/accounts/{plain['id']}", json={"new_accounts_in_budget": True}).status_code == 400
    assert client.patch(f"/api/accounts/{group['id']}", json={"new_accounts_in_budget": None}).status_code == 400


def test_the_names_of_siblings_are_unique_and_a_group_takes_no_entries(client, root_accounts):
    group = make_group(client).json()
    assert make_group(client, "family").status_code == 400
    assert make_group(client, "Cash").status_code == 400, "a built-in group already has the name"
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "50"}).json()
    entry = {
        "date": "2026-11-01",
        "postings": [
            {"account_id": group["id"], "side": "debit", "amount": "5"},
            {"account_id": bank["id"], "side": "credit", "amount": "5"},
        ],
    }
    refused = client.post("/api/transactions/", json=entry)
    assert refused.status_code == 400 and "group" in refused.json()["detail"]


def test_an_empty_group_can_be_deleted_but_not_one_with_accounts(client):
    group = make_group(client).json()
    inside = in_group(client, group, "Wallet").json()
    assert client.delete(f"/api/accounts/{group['id']}").status_code == 409
    assert client.delete(f"/api/accounts/{inside['id']}").status_code == 204
    assert client.delete(f"/api/accounts/{group['id']}").status_code == 204


def test_the_built_in_groups_carry_the_choice_they_always_had(client):
    found = {
        a["system_key"]: a["new_accounts_in_budget"] for a in client.get("/api/accounts/").json() if a["system_key"]
    }
    assert found == {
        "assets.bank": True,
        "assets.cash": True,
        "assets.investments": False,
        "liabilities.cards": True,
        "liabilities.loans": False,
    }


def test_a_group_survives_a_backup_with_its_choice_even_when_empty(client):
    make_group(client, "Family", budget=False)
    doc = client.get("/api/backup").json()
    assert next(a for a in doc["accounts"] if a["name"] == "Family")["new_accounts_in_budget"] is False
    assert restore_as_other(client, doc).status_code == 200
    try:
        as_user(OTHER)
        restored = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Family")
        assert restored["new_accounts_in_budget"] is False
    finally:
        as_user(TEST_USER_ID)


# ---- the pages ----------------------------------------------------------------------------------------------------


def test_the_new_group_form_chooses_nothing_for_the_person(client):
    page = client.get("/accounts/new-group").text
    assert "Money I own" in page and "Money I owe" in page and "Part of the budget" in page
    assert "checked" not in page and 'name="balance"' not in page


def test_creating_a_group_from_the_form_and_its_errors(client):
    sent = {"name": "Family", "holds": "own", "new_accounts_in_budget": "1"}
    assert client.post("/accounts/new-group", data={**sent, "holds": ""}).headers.get("HX-Retarget") == "#form-error"
    refused = client.post("/accounts/new-group", data={**sent, "holds": ""})
    assert "money you own or money you owe" in refused.text
    done = client.post("/accounts/new-group", data=sent)
    assert done.headers["HX-Redirect"].startswith("/accounts")
    again = client.post("/accounts/new-group", data=sent)
    assert "already has an account called" in again.text
    made = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Family")
    assert made["new_accounts_in_budget"] is True
    off = client.post("/accounts/new-group", data={"name": "Dues", "holds": "owe"})
    assert off.headers["HX-Redirect"].startswith("/accounts")
    owed = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Dues")
    assert owed["new_accounts_in_budget"] is False


def test_an_empty_group_is_a_shelf_with_only_the_add_card(client):
    group = make_group(client).json()
    page = client.get("/accounts").text
    assert "<h2>Family</h2>" in page and "0.00 · 0 accounts" in page
    shelf = page.split("<h2>Family</h2>", 1)[1].split("</section>", 1)[0]
    assert shelf.count('class="acc-card') == 1 and f'href="/accounts/new?parent={group["id"]}"' in shelf
    assert 'class="add-row" href="/accounts/new-group"' in page
    assert 'class="add-row" href="/accounts/new"' not in page


def test_the_five_built_in_shelves_always_show(client):
    heads = re.findall(r"<h2>([^<]+)</h2>", client.get("/accounts").text)
    assert heads == ["Bank Accounts", "Cash", "Credit Cards", "Investments", "Loans"]


def test_an_account_form_opened_for_a_group_starts_as_the_group_says(client):
    out = make_group(client, "Out", budget=False).json()
    page = client.get(f"/accounts/new?parent={out['id']}").text
    assert f'<option value="{out["id"]}" selected data-root="Assets" data-start="outside">' in page
    assert re.search(r'name="on_budget"[^>]*>', page) and 'name="on_budget" value="1" checked' not in page


def test_a_groups_page_edits_its_name_and_choice_and_deletes_it_when_empty(client):
    group = make_group(client).json()
    page = client.get(f"/accounts/{group['id']}").text
    assert "Group · money I own" in page and "Sub-accounts" in page and "Nothing here yet" in page
    form = client.get(f"/accounts/{group['id']}/edit").text
    assert 'name="new_accounts_in_budget"' in form and 'name="balance"' not in form
    saved = client.post(f"/accounts/{group['id']}/edit", data={"name": "Kin", "group_choice": "1"})
    assert saved.headers["HX-Redirect"] == f"/accounts/{group['id']}"
    now = client.get(f"/api/accounts/{group['id']}").json()
    assert now["name"] == "Kin" and now["new_accounts_in_budget"] is False
    assert client.post(f"/accounts/{group['id']}/delete").headers["HX-Redirect"] == "/accounts"


def test_a_group_never_appears_where_entries_are_posted(client):
    group = make_group(client).json()
    assert group["id"] not in client.get("/transactions/new").text
