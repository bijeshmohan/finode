import pytest
from fastapi.testclient import TestClient

from app.config import settings


def _make(client: TestClient, name: str, parent: str) -> dict:
    return client.post("/api/accounts/", json={"name": name, "parent_id": parent})


def _limit(client: TestClient, **limits: int):
    return client.patch("/api/profile/", json={f"max_depth_{k}": v for k, v in limits.items()})


@pytest.fixture
def cap(monkeypatch):
    def set_cap(value: int):
        monkeypatch.setattr(settings, "max_account_depth", value)
    return set_cap


def test_default_is_unlimited_up_to_the_application_maximum(client: TestClient, root_accounts):
    assert client.get("/api/profile/").json()["max_depth_expenses"] == 0
    parent = root_accounts["Expenses"]
    for level in range(1, settings.max_account_depth + 1):
        response = _make(client, f"l{level}", parent)
        assert response.status_code == 201, level
        parent = response.json()["aid"]
    assert _make(client, "too-deep", parent).status_code == 400


def test_limit_blocks_new_sub_accounts_beyond_it(client: TestClient, root_accounts):
    assert _limit(client, expenses=2).status_code == 200
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    groceries = _make(client, "Groceries", food["aid"])
    assert groceries.status_code == 201
    response = _make(client, "Veg", groceries.json()["aid"])
    assert response.status_code == 400
    assert "Expenses accounts can be at most 2 levels deep, and this would be 3" in response.json()["detail"]


def test_limit_of_one_means_flat(client: TestClient, root_accounts):
    _limit(client, assets=1)
    bank = _make(client, "Bank", root_accounts["Assets"]).json()
    assert _make(client, "HDFC", bank["aid"]).status_code == 400


def test_limits_are_per_top_level_account(client: TestClient, root_accounts):
    _limit(client, expenses=1)
    bank = _make(client, "Bank", root_accounts["Assets"]).json()
    assert _make(client, "HDFC", bank["aid"]).status_code == 201


def test_cannot_set_limit_below_existing_depth(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    _make(client, "Groceries", food["aid"])
    response = _limit(client, expenses=1)
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "cannot limit Expenses to 1 level" in detail and "Expenses › Food › Groceries" in detail
    assert "choose at least 2" in detail
    assert client.get("/api/profile/").json()["max_depth_expenses"] == 0
    assert _limit(client, expenses=2).status_code == 200
    assert _limit(client, expenses=0).status_code == 200


def test_lowering_one_root_ignores_other_roots(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    _make(client, "Groceries", food["aid"])
    assert _limit(client, assets=1).status_code == 200


def test_invalid_values_are_rejected(client: TestClient):
    assert _limit(client, expenses=-1).status_code == 422
    assert client.patch("/api/profile/", json={"max_depth_expenses": None}).status_code == 422
    assert client.patch("/api/profile/", json={"max_depth_expenses": "abc"}).status_code == 422


def test_users_cannot_exceed_the_application_maximum(client: TestClient, cap):
    cap(3)
    response = _limit(client, expenses=4)
    assert response.status_code == 400
    assert "at most 3 levels" in response.json()["detail"]
    assert _limit(client, expenses=3).status_code == 200


def test_zero_means_the_application_maximum(client: TestClient, root_accounts, cap):
    cap(2)
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    groceries = _make(client, "Groceries", food["aid"]).json()
    assert _make(client, "Veg", groceries["aid"]).status_code == 400


def test_moving_a_subtree_respects_the_limit(client: TestClient, root_accounts):
    _limit(client, expenses=2)
    a = _make(client, "A", root_accounts["Expenses"]).json()
    b = _make(client, "B", root_accounts["Expenses"]).json()
    c = _make(client, "C", b["aid"]).json()
    # B (with C below it) under A would be 3 levels deep
    response = client.patch(f"/api/accounts/{b['aid']}", json={"parent_id": a["aid"]})
    assert response.status_code == 400 and "this would be 3" in response.json()["detail"]
    # C alone under A is 2 levels
    assert client.patch(f"/api/accounts/{c['aid']}", json={"parent_id": a["aid"]}).status_code == 200


def test_import_respects_limits(client: TestClient):
    _limit(client, expenses=1)
    text = "2026-01-01 x\n    Expenses:Food:Groceries  5\n    Assets:Cash\n"
    response = client.post("/api/import", files={"file": ("a.ledger", text.encode())}, params={"dry_run": "true"})
    errors = response.json()["errors"]
    assert errors and "Expenses:Food:Groceries" in errors[0] and "allows 1" in errors[0]
    assert "Profile › Account depth" in errors[0]


# --- web ------------------------------------------------------------------


def test_settings_page_shows_depth_card_with_hints(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    _make(client, "Groceries", food["aid"])
    text = client.get("/settings").text
    assert 'name="max_depth_expenses"' in text and "Deepest now: 2" in text
    assert "No sub-accounts yet" in text
    assert f'max="{settings.max_account_depth}"' in text


def test_saving_depth_limits_redirects_with_flash(client: TestClient):
    response = client.post("/settings/depth", data={"max_depth_expenses": "2", "max_depth_assets": "0"})
    assert response.headers["HX-Redirect"] == "/settings#depth"
    assert "depth-updated" in response.headers["set-cookie"]
    assert client.get("/api/profile/").json()["max_depth_expenses"] == 2


@pytest.mark.parametrize("value,fragment", [("-1", "cannot be negative"), ("abc", "not a whole number")])
def test_web_depth_validation_messages(client: TestClient, value, fragment):
    response = client.post("/settings/depth", data={"max_depth_income": value})
    assert response.status_code == 400 and fragment in response.text
    assert response.headers["HX-Retarget"] == "#depth-error"


def test_web_refuses_limit_below_existing_depth(client: TestClient, root_accounts):
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    _make(client, "Groceries", food["aid"])
    response = client.post("/settings/depth", data={"max_depth_expenses": "1"})
    assert response.status_code == 400 and "Expenses › Food › Groceries" in response.text


def test_parent_pickers_leave_out_accounts_at_the_limit(client: TestClient, root_accounts):
    _limit(client, expenses=2)
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    groceries = _make(client, "Groceries", food["aid"]).json()
    for url in ("/accounts/new", "/accounts/quick"):
        text = client.get(url).text
        assert f'value="{food["aid"]}"' in text
        assert f'value="{groceries["aid"]}"' not in text


def test_account_page_hides_add_sub_account_at_the_limit(client: TestClient, root_accounts):
    _limit(client, expenses=2)
    food = _make(client, "Food", root_accounts["Expenses"]).json()
    groceries = _make(client, "Groceries", food["aid"]).json()
    at_limit = client.get(f"/accounts/{groceries['aid']}").text
    assert f"/accounts/new?parent={groceries['aid']}" not in at_limit
    assert "can be 2 levels deep" in at_limit and "/settings#depth" in at_limit
    below = client.get(f"/accounts/{food['aid']}").text
    assert f"/accounts/new?parent={food['aid']}" in below


def test_edit_form_offers_only_parents_that_fit_the_moved_subtree(client: TestClient, root_accounts):
    _limit(client, expenses=2)
    a = _make(client, "A", root_accounts["Expenses"]).json()
    b = _make(client, "B", root_accounts["Expenses"]).json()
    _make(client, "C", b["aid"])
    text = client.get(f"/accounts/{b['aid']}/edit").text
    assert f'value="{a["aid"]}"' not in text  # B has a child, so under A it would be 3 deep
    assert f'value="{root_accounts["Expenses"]}"' in text
