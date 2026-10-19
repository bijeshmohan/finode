"""Accounts are two levels deep at most: a category and a subcategory (Expenses › Food › Groceries)."""

import json

import pytest
from fastapi.testclient import TestClient

from .test_backup import as_user, OTHER
from .conftest import TEST_USER_ID


def _make(client: TestClient, name: str, parent: str):
    return client.post("/api/accounts/", json={"name": name, "parent_id": parent})


@pytest.mark.parametrize("root", ["Expenses", "Income", "Assets", "Liabilities", "Equity"])
def test_every_type_stops_at_two_levels(client: TestClient, root_accounts, root):
    level1 = _make(client, "One", root_accounts[root])
    assert level1.status_code == 201
    level2 = _make(client, "Two", level1.json()["aid"])
    assert level2.status_code == 201
    refused = _make(client, "Three", level2.json()["aid"])
    assert refused.status_code == 400
    assert "at most two levels deep" in refused.json()["detail"] and "category and a subcategory" in refused.json()["detail"]


def test_there_is_no_depth_setting_any_more(client: TestClient):
    profile = client.get("/api/profile/").json()
    assert not [k for k in profile if "depth" in k]
    client.patch("/api/profile/", json={"max_depth_expenses": 1})  # an old client: ignored
    food = _make(client, "Food", client.get("/api/accounts/").json()[0]["aid"]).json()
    assert food["parent_id"]
    advanced = client.get("/settings/advanced").text
    assert 'id="depth"' not in advanced and "Account depth" not in advanced
    assert client.post("/settings/depth", data={"max_depth_expenses": "1"}).status_code in (404, 405)


def test_moving_a_subtree_respects_the_two_levels(client: TestClient, root_accounts):
    a = _make(client, "A", root_accounts["Expenses"]).json()
    b = _make(client, "B", root_accounts["Expenses"]).json()
    c = _make(client, "C", b["aid"]).json()
    # B (with C below it) under A would be 3 levels deep
    refused = client.patch(f"/api/accounts/{b['aid']}", json={"parent_id": a["aid"]})
    assert refused.status_code == 400 and "at most two levels deep" in refused.json()["detail"]
    # C alone under A is 2 levels
    assert client.patch(f"/api/accounts/{c['aid']}", json={"parent_id": a["aid"]}).status_code == 200


def test_import_refuses_a_third_level(client: TestClient):
    text = "2026-01-01 x\n    Expenses:Food:Dining:Takeaway  5\n    Assets:Cash\n"
    response = client.post("/api/import", files={"file": ("a.ledger", text.encode())}, params={"dry_run": "true"})
    errors = response.json()["errors"]
    assert errors and "Expenses:Food:Dining:Takeaway" in errors[0] and "at most 2 levels deep" in errors[0]
    fine = "2026-01-01 x\n    Expenses:Food:Dining  5\n    Assets:Cash\n"
    assert client.post("/api/import", files={"file": ("a.ledger", fine.encode())}, params={"dry_run": "true"}).json()["errors"] == []


def test_a_restore_refuses_a_third_level_and_ignores_old_limits(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    dining = _make(client, "Dining", food["aid"]).json()
    doc = client.get("/api/backup").json()
    assert not [k for k in doc["profile"] if "depth" in k]
    deep = json.loads(json.dumps(doc))
    deep["accounts"].append({"id": "00000000-0000-4000-8000-0000000000d3", "parent_id": dining["aid"], "name": "Takeaway"})
    old = json.loads(json.dumps(doc))
    old["profile"]["max_depth_expenses"] = 1  # what an older backup carries
    try:
        as_user(OTHER)
        refused = client.post("/api/restore", files={"file": ("b.json", json.dumps(deep), "application/json")})
        assert refused.status_code == 400 and "at most 2 levels deep" in str(refused.json())
        assert client.post("/api/restore", files={"file": ("b.json", json.dumps(old), "application/json")}).status_code == 200
    finally:
        as_user(TEST_USER_ID)


# --- web ------------------------------------------------------------------


def test_parent_pickers_leave_out_accounts_that_cannot_hold_more(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    groceries = _make(client, "Groceries", food["aid"]).json()
    for url in ("/categories/new", "/accounts/quick"):
        text = client.get(url).text
        assert f'value="{food["aid"]}"' in text
        assert f'value="{groceries["aid"]}"' not in text


def test_account_page_offers_sub_accounts_only_where_there_is_room(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    groceries = _make(client, "Groceries", food["aid"]).json()
    bottom = client.get(f"/categories/{groceries['aid']}").text
    assert f"/categories/new?parent={groceries['aid']}" not in bottom and "levels deep" not in bottom
    assert f"/categories/new?parent={food['aid']}" in client.get(f"/categories/{food['aid']}").text


def test_edit_form_offers_only_parents_that_fit_the_moved_subtree(client: TestClient, root_accounts):
    a = _make(client, "A", root_accounts["Expenses"]).json()
    b = _make(client, "B", root_accounts["Expenses"]).json()
    _make(client, "C", b["aid"])
    text = client.get(f"/accounts/{b['aid']}/edit").text
    assert f'value="{a["aid"]}"' not in text  # B has a child, so under A it would be 3 deep
    assert f'value="{root_accounts["Expenses"]}"' in text
