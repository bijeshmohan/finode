"""/api/views/budget, /api/views/budget/groups/{category_id} and /api/views/budget-move: what the finode app's Budgets
pages show, worked out by services/budget_view.py."""

from datetime import date

import pytest

from tests.budget.test_budget import account, assign
from tests.budget.test_budget import budget as api_budget
from tests.guards.test_isolation import B_USER, signed_in_as

THIS_MONTH = date.today().replace(day=1)


@pytest.fixture
def setup(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="1000")
    food = account(client, root_accounts, "Food", "Expenses")
    rent = account(client, root_accounts, "Rent", "Expenses")
    return {"bank": bank, "food": food, "rent": rent}


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
    assert "is_group" not in rent and "unused" not in rent and "unused_count" not in seen


def test_nothing_assigned_reads_so(client, setup):
    seen = view(client)
    assert rows(seen)["Food"]["of"] is None and rows(seen)["Food"]["hint"] == ""


def test_the_move_view(client, setup):
    assign(client, setup["food"], "100")
    seen = view(client, "/api/views/budget-move", source=setup["food"]["id"])
    assert seen["source"] == setup["food"]["id"]
    assert {(ln["name"], ln["available"]) for ln in seen["lines"]} >= {("Food", "100.00"), ("Rent", "0.00")}
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
    with signed_in_as(B_USER):
        assert "Food" not in client.get("/api/views/budget").text
    assert client.get(f"/api/views/budget/groups/{setup['rent']['id']}").status_code == 404, "not a group"
    assert view(client, month="13-2026")["month"] == THIS_MONTH.strftime("%Y-%m")


# Ported from test_web_budget.py (the old Budgets pages), step 10.


def test_only_a_category_takes_an_amount(client, setup):
    assert client.put(f"/api/budget/categories/{setup['bank']['id']}", json={"amount": "5"}).status_code in (400, 404)
    assert client.put(f"/api/budget/categories/{setup['food']['id']}", json={"amount": "lots"}).status_code == 422


def test_one_overspent_category_is_not_overspending_overall_but_more_spent_than_assigned_is(client, setup):
    from tests.budget.test_budget import move

    assign(client, setup["food"], "100")
    assign(client, setup["rent"], "500")
    move(client, setup["bank"], setup["food"], "150")
    seen = view(client)
    assert seen["overspent"] == "0.00" and rows(seen)["Food"]["state"] == "overspent"
    move(client, setup["bank"], setup["food"], "600")
    assert view(client)["overspent"] == "150.00"
