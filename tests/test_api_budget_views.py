"""/api/views/budget, /api/views/budget/groups/{category_id} and /api/views/budget-move: what the finode app's Budgets
pages show, worked out as the web pages work it out (services/budget_view.py)."""

from datetime import date

from .books import post_account
from .test_budget import account, assign
from .test_budget import budget as api_budget
from .test_isolation import B_USER, signed_in_as
from .test_web_budget import THIS_MONTH, setup  # noqa: F401  # setup is a fixture


def view(client, path="/api/views/budget", **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def rows(seen):
    return {r["name"]: r for r in seen["rows"]}


def test_the_head(client, setup):
    seen = view(client)
    assert (seen["month"], seen["is_current"], seen["ready_to_assign"]) == (
        THIS_MONTH.strftime("%Y-%m"),
        True,
        "1000.00",
    )
    assert seen["sum"] == {
        "money_in_accounts": "1000.00",
        "reserved_for_cards": "0.00",
        "available": "0.00",
        "assigned_to_later_months": "0.00",
    }
    assert seen["show_intro"] is True and seen["has_budget_accounts"] is True and isinstance(seen["pace"], int)
    assign(client, setup["food"], "300")
    seen = view(client)
    assert seen["show_intro"] is False and seen["ready_to_assign"] == "700.00"


def test_over_assigned_and_overspent(client, setup):
    assign(client, setup["food"], "1200")
    seen = view(client)
    assert seen["ready_to_assign"] == "-200.00" and seen["overspent"] == "0.00"
    past = view(client, month="2020-01")
    assert past["is_current"] is False and past["pace"] is None


def test_the_rows_read_as_the_page(client, setup):
    assign(client, setup["rent"], "500")
    assign(client, setup["food"], "100")
    client.post(
        "/api/transactions/",
        json={
            "date": date.today().isoformat(),
            "postings": [
                {"category_id": setup["food"]["id"], "side": "debit", "amount": "100"},
                {"account_id": setup["bank"]["id"], "side": "credit", "amount": "100"},
            ],
        },
    )
    seen = view(client)
    assert [r["name"] for r in seen["rows"]] == ["Rent", "Food"], "biggest budget first"
    rent, food = rows(seen)["Rent"], rows(seen)["Food"]
    assert (rent["of"], rent["state"], rent["percent"], rent["over"]) == ("500.00", None, 0, False)
    assert (food["of"], food["state"], food["percent"], food["available"]) == ("100.00", "all_spent", 100, "0.00")
    assert rent["is_group"] is False and rent["unused"] is False


def test_nothing_assigned_reads_so(client, setup):
    seen = view(client)
    assert rows(seen)["Food"]["of"] is None and rows(seen)["Food"]["hint"] == ""


def test_unused_groups_are_marked_once_anything_is_used(client, root_accounts, setup):
    travel = account(client, root_accounts, "Travel", "Expenses")
    post_account(client, {"name": "Stay", "parent_id": travel["id"]})
    assert view(client)["unused_count"] == 0, "nothing in use yet: everything shows"
    assign(client, setup["food"], "100")
    seen = view(client)
    assert seen["unused_count"] == 1 and rows(seen)["Travel"]["unused"] is True and rows(seen)["Travel"]["is_group"]
    assert rows(seen)["Rent"]["unused"] is False, "a plain category always shows"


def test_a_groups_view(client, setup):
    groceries = post_account(client, {"name": "Groceries", "parent_id": setup["food"]["id"]}).json()
    dining = post_account(client, {"name": "Dining", "parent_id": setup["food"]["id"]}).json()
    assign(client, groceries, "200")
    assign(client, dining, "300")
    seen = view(client, f"/api/views/budget/groups/{setup['food']['id']}")
    assert (seen["name"], seen["minimum"], seen["assigned"]) == ("Food", "500.00", "500.00")
    assert seen["glance"] == {"left": "500.00", "spent": "0.00", "of": "500.00", "percent": 0, "planned": True}
    assert [k["name"] for k in seen["kids"]] == ["Dining", "Groceries"]
    assert rows(view(client))["Food"]["hint"] == "Dining · Groceries"


def test_the_move_view(client, setup):
    assign(client, setup["food"], "100")
    seen = view(client, "/api/views/budget-move", source=setup["food"]["id"])
    assert seen["source"] == setup["food"]["id"]
    assert {(ln["path"], ln["available"]) for ln in seen["lines"]} >= {("Food", "100.00"), ("Rent", "0.00")}
    assert client.get("/api/views/budget-move", params={"source": setup["bank"]["id"]}).status_code == 404


def test_moving_keeps_ready_to_assign(client, setup):
    assign(client, setup["food"], "300")
    before = view(client)["ready_to_assign"]
    moved = client.post(
        "/api/budget/move",
        json={"from_category": setup["food"]["id"], "to_category": setup["rent"]["id"], "amount": "100"},
    )
    assert moved.status_code == 200, moved.text
    seen = view(client)
    assert seen["ready_to_assign"] == before and rows(seen)["Rent"]["available"] == "100.00"
    assert api_budget(client)["ready_to_assign"] == before


def test_strangers_and_bad_months(client, setup):
    groceries = post_account(client, {"name": "Groceries", "parent_id": setup["food"]["id"]}).json()
    assert groceries
    with signed_in_as(B_USER):
        assert client.get(f"/api/views/budget/groups/{setup['food']['id']}").status_code == 404
        assert "Food" not in client.get("/api/views/budget").text
    assert client.get(f"/api/views/budget/groups/{setup['rent']['id']}").status_code == 404, "not a group"
    assert view(client, month="13-2026")["month"] == THIS_MONTH.strftime("%Y-%m")
