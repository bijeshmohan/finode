"""Accounts are two levels deep at most (Assets › Banks › HDFC), and so are categories (Food › Groceries)."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.books import post_account
from tests.conftest import TEST_USER_ID
from tests.data.test_backup import OTHER, as_user


def _make(client: TestClient, name: str, parent: str):
    return post_account(client, {"name": name, "parent_id": parent})


@pytest.mark.parametrize("root", ["Assets", "Liabilities", "Equity", "Expenses", "Income"])
def test_every_type_stops_at_two_levels(client: TestClient, root_accounts, root):
    level1 = _make(client, "One", root_accounts[root])
    assert level1.status_code == 201
    level2 = _make(client, "Two", level1.json()["id"])
    assert level2.status_code == 201
    refused = _make(client, "Three", level2.json()["id"])
    assert refused.status_code == 400
    assert "at most two levels deep" in refused.json()["detail"]


def test_there_is_no_depth_setting_any_more(client: TestClient):
    profile = client.get("/api/profile/").json()
    assert not [k for k in profile if "depth" in k]
    client.patch("/api/profile/", json={"max_depth_expenses": 1})  # an old client: ignored
    food = _make(client, "Food", client.get("/api/accounts/").json()[0]["id"]).json()
    assert food["parent_id"]


def test_moving_a_subtree_respects_the_two_levels(client: TestClient, root_accounts):
    a = _make(client, "A", root_accounts["Assets"]).json()
    b = _make(client, "B", root_accounts["Assets"]).json()
    c = _make(client, "C", b["id"]).json()
    # B (with C below it) under A would be 3 levels deep
    refused = client.patch(f"/api/accounts/{b['id']}", json={"parent_id": a["id"]})
    assert refused.status_code == 400 and "at most two levels deep" in refused.json()["detail"]
    # C alone under A is 2 levels
    assert client.patch(f"/api/accounts/{c['id']}", json={"parent_id": a["id"]}).status_code == 200


def test_moving_a_category_with_subcategories_inside_another_is_refused(client: TestClient, root_accounts):
    a = _make(client, "A", root_accounts["Expenses"]).json()
    b = _make(client, "B", root_accounts["Expenses"]).json()
    c = _make(client, "C", b["id"]).json()
    refused = client.patch(f"/api/categories/{b['id']}", json={"parent_id": a["id"]})
    assert refused.status_code == 400 and "at most two levels deep" in refused.json()["detail"]
    assert client.patch(f"/api/categories/{c['id']}", json={"parent_id": a["id"]}).status_code == 200


def test_import_refuses_a_third_level(client: TestClient):
    text = "2026-01-01 x\n    Expenses:Food:Dining:Takeaway  5\n    Assets:Cash\n"
    response = client.post("/api/import", files={"file": ("a.ledger", text.encode())}, params={"dry_run": "true"})
    errors = response.json()["errors"]
    assert errors and "Expenses:Food:Dining:Takeaway" in errors[0] and "at most 2 levels deep" in errors[0]
    fine = "2026-01-01 x\n    Expenses:Food:Dining  5\n    Assets:Cash\n"
    assert (
        client.post("/api/import", files={"file": ("a.ledger", fine.encode())}, params={"dry_run": "true"}).json()[
            "errors"
        ]
        == []
    )


def test_a_restore_refuses_a_third_level_and_ignores_old_limits(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    dining = _make(client, "Dining", food["id"]).json()
    doc = client.get("/api/backup").json()
    assert not [k for k in doc["profile"] if "depth" in k]
    deep = json.loads(json.dumps(doc))
    deep["categories"].append(
        {
            "id": "00000000-0000-4000-8000-0000000000d3",
            "parent_id": dining["id"],
            "name": "Takeaway",
            "kind": "spending",
        }
    )
    old = json.loads(json.dumps(doc))
    old["profile"]["max_depth_expenses"] = 1  # what an older backup carries
    try:
        as_user(OTHER)
        refused = client.post("/api/restore", files={"file": ("b.json", json.dumps(deep), "application/json")})
        assert refused.status_code == 400 and "at most 2 levels deep" in str(refused.json())
        assert (
            client.post("/api/restore", files={"file": ("b.json", json.dumps(old), "application/json")}).status_code
            == 200
        )
    finally:
        as_user(TEST_USER_ID)


# --- web ------------------------------------------------------------------


def test_parent_pickers_leave_out_accounts_that_cannot_hold_more(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    groceries = _make(client, "Groceries", food["id"]).json()
    groups = {g["id"] for g in client.get("/api/views/category-form").json()["groups"]}
    pickers = {g["id"] for g in client.get("/api/views/entry-form").json()["category_parents"]}
    for offered in (groups, pickers):
        assert food["id"] in offered and groceries["id"] not in offered


def test_a_category_offers_subcategories_only_where_there_is_room(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    groceries = _make(client, "Groceries", food["id"]).json()
    assert client.get(f"/api/views/categories/{groceries['id']}").json()["can_add_child"] is False
    assert client.get(f"/api/views/categories/{food['id']}").json()["can_add_child"] is True


def test_edit_form_of_a_group_offers_no_new_parent(client: TestClient, root_accounts):
    a = _make(client, "A", root_accounts["Assets"]).json()
    b = _make(client, "B", root_accounts["Assets"]).json()
    _make(client, "C", b["id"])
    form = client.get("/api/views/account-form", params={"account_id": b["id"]}).json()
    assert form["is_group"] is True and form["parent_options"] == [], "a group stays where it is"
    assert a["id"] not in {k["id"] for k in form["kinds"]}, "B has a child: under A it would be 3 deep"


def test_the_category_form_offers_only_categories_that_can_hold_subcategories(client: TestClient, root_accounts):
    a = _make(client, "A", root_accounts["Expenses"]).json()
    b = _make(client, "B", root_accounts["Expenses"]).json()
    _make(client, "C", b["id"])
    form = client.get("/api/views/category-form", params={"category_id": b["id"]}).json()
    assert a["id"] not in {g["id"] for g in form["groups"]}, "B holds a subcategory, so it cannot go inside A"
