"""Groups the person makes: a shelf for accounts that can stand empty, holds money owned or owed, and says whether the
accounts made in it start in the budget."""

import pytest

from finode.services import account as account_service
from tests.books import post_account
from tests.conftest import TEST_USER_ID
from tests.data.test_backup import OTHER, as_user, restore_as_other


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


# ---- what the app's pages show (/api/views), ported from the old pages' tests, step 10 ------------------------------


def accounts_view(client) -> dict:
    answer = client.get("/api/views/accounts")
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_an_empty_group_is_a_shelf_of_its_own(client):
    group = make_group(client).json()
    family = next(k for k in accounts_view(client)["kinds"] if k["name"] == "Family")
    assert (family["total"], family["open_count"], family["cards"]) == ("0.00", 0, [])
    assert family["group_id"] == group["id"] and family["add_url"] == f"/accounts/new?parent={group['id']}"


def test_the_five_built_in_shelves_always_show(client):
    assert [k["name"] for k in accounts_view(client)["kinds"]] == [
        "Bank Accounts",
        "Cash",
        "Credit Cards",
        "Investments",
        "Loans",
    ]


def test_every_group_heading_opens_its_page_but_the_other_row_has_none(client, root_accounts):
    group = make_group(client).json()
    post_account(client, {"name": "Loose", "parent_id": root_accounts["Assets"]})
    cash = next(a for a in client.get("/api/accounts/").json() if a["system_key"] == "assets.cash")
    heads = {k["name"]: k["group_id"] for k in accounts_view(client)["kinds"]}
    assert heads["Family"] == group["id"] and heads["Cash"] == cash["id"] and heads["Other"] is None


def test_an_account_form_opened_for_a_group_starts_as_the_group_says(client):
    out = make_group(client, "Out", budget=False).json()
    form = client.get("/api/views/account-form", params={"parent": out["id"]}).json()
    assert form["parent_id"] == out["id"] and form["on_budget"] is False


def test_a_groups_page_lists_the_transactions_of_its_accounts_with_the_account_named(client, root_accounts):
    group = make_group(client).json()
    wallet = in_group(client, group, "Mom's wallet", balance="100").json()
    other = in_group(client, group, "Dad's wallet").json()
    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "500"}).json()

    def move(source, target, payee, amount="10"):
        legs = [
            {"account_id": target["id"], "side": "debit", "amount": amount},
            {"account_id": source["id"], "side": "credit", "amount": amount},
        ]
        return client.post("/api/transactions/", json={"date": "2026-11-01", "payee": payee, "postings": legs})

    assert move(bank, wallet, "Pocket money").status_code == 201
    assert move(wallet, other, "Between us").status_code == 201
    spare = post_account(client, {"name": "Spare", "parent_id": root_accounts["Assets"]}).json()
    assert move(bank, spare, "Not ours").status_code == 201
    page = client.get(f"/api/views/accounts/{group['id']}").json()
    titles = [r["title"] for r in page["entries"]]
    assert "Pocket money" in titles and "Not ours" not in titles
    assert titles.count("Between us") == 1, "a transfer inside the group shows once"
    pocket = next(r for r in page["entries"] if r["title"] == "Pocket money")
    assert pocket["sub"] == "Mom's wallet · Bank", "the account first, then the other side"
    assert page["has_more"] is False


def test_only_a_group_you_made_can_be_edited(client):
    group = make_group(client).json()
    cash = next(a for a in client.get("/api/accounts/").json() if a["system_key"] == "assets.cash")
    assert client.get(f"/api/views/accounts/{group['id']}").json()["can_edit"] is True
    assert client.get(f"/api/views/accounts/{cash['id']}").json()["can_edit"] is False


def test_a_group_never_appears_where_entries_are_posted(client):
    group = make_group(client).json()
    form = client.get("/api/views/entry-form").json()
    assert group["id"] not in {o["id"] for g in form["groups"] for o in g["options"]}
