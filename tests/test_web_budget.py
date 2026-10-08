"""The budget page: reading it, assigning inline, moving money, and switching accounts in."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from .test_budget import account, assign, line, move, budget as api_budget

THIS_MONTH = date.today().replace(day=1)


@pytest.fixture
def setup(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="1000")
    food = account(client, root_accounts, "Food", "Expenses")
    rent = account(client, root_accounts, "Rent", "Expenses")
    return {"bank": bank, "food": food, "rent": rent}


def test_the_page_shows_what_is_left_to_assign(client, setup):
    page = client.get("/budget").text
    assert "Ready to assign" in page and "1,000.00" in page.replace("1000.00", "1,000.00")
    assert "Food" in page and "Rent" in page and "this month" in page
    assert 'href="/budget?month=' in page


def test_an_empty_budget_says_how_to_start(client, root_accounts):
    page = client.get("/budget").text
    assert "No account is part of the budget yet" in page


def test_assigning_inline_returns_the_updated_block(client, setup):
    response = client.post(
        "/budget/assign", data={"category": setup["food"]["aid"], "month": THIS_MONTH.strftime("%Y-%m"), "amount": "300"}
    )
    assert response.status_code == 200 and 'id="budget"' in response.text
    assert "700.00" in response.text and 'value="300.00"' in response.text
    assert line(api_budget(client), "Food")["assigned"] == "300.00"


def test_clearing_the_field_removes_the_amount(client, setup):
    assign(client, setup["food"], "300")
    client.post("/budget/assign", data={"category": setup["food"]["aid"], "month": "", "amount": ""})
    assert line(api_budget(client), "Food")["assigned"] == "0.00"


def test_a_bad_amount_is_explained_next_to_the_list(client, setup):
    response = client.post("/budget/assign", data={"category": setup["food"]["aid"], "amount": "lots"})
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#budget-error"
    assert "not a valid amount" in response.text
    response = client.post("/budget/assign", data={"category": setup["bank"]["aid"], "amount": "5"})
    assert response.status_code == 400 and "expense" in response.text


def test_other_months_are_reachable(client, setup):
    last = (THIS_MONTH - timedelta(days=1)).strftime("%Y-%m")
    page = client.get(f"/budget?month={last}").text
    assert (THIS_MONTH - timedelta(days=1)).strftime("%B %Y") in page and "this month" not in page
    assert "this month" in client.get("/budget?month=nonsense").text, "unreadable falls back to now"


def test_overspending_and_overassigning_are_called_out(client, setup):
    assign(client, setup["food"], "1500")
    page = client.get("/budget").text
    assert "more than you have" in page and "ready over" in page


def test_every_unit_with_a_job_is_celebrated(client, setup):
    assign(client, setup["food"], "1000")
    assert "has a job" in client.get("/budget").text


def test_the_move_page_lists_the_categories_and_moves_money(client, setup):
    assign(client, setup["food"], "300")
    page = client.get(f"/budget/move?source={setup['food']['aid']}").text
    assert "Move money" in page and f'value="{setup["food"]["aid"]}" selected' in page
    done = client.post(
        "/budget/move",
        data={"from_category": setup["food"]["aid"], "to_category": setup["rent"]["aid"], "amount": "100", "month": ""},
    )
    assert done.status_code == 200 and done.headers["HX-Redirect"].startswith("/budget")
    data = api_budget(client)
    assert line(data, "Food")["available"] == "200.00" and line(data, "Rent")["available"] == "100.00"


def test_moving_more_than_available_is_refused_in_the_form(client, setup):
    assign(client, setup["food"], "50")
    bad = client.post(
        "/budget/move",
        data={"from_category": setup["food"]["aid"], "to_category": setup["rent"]["aid"], "amount": "80"},
    )
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#form-error" and "only 50.00" in bad.text


def test_an_unknown_source_is_a_404(client, setup):
    assert client.get("/budget/move?source=00000000-0000-4000-8000-0000000000aa").status_code == 404


def test_the_account_page_can_switch_the_budget_on_and_off(client, root_accounts, setup):
    page = client.get(f"/accounts/{setup['bank']['aid']}/edit").text
    assert "Part of the budget" in page and "checked" in page
    off = client.post(f"/accounts/{setup['bank']['aid']}/edit", data={"name": "Bank", "budget_choice": "1"})
    assert off.status_code == 200
    assert client.get(f"/api/accounts/{setup['bank']['aid']}").json()["on_budget"] is False
    on = client.post(f"/accounts/{setup['bank']['aid']}/edit", data={"name": "Bank", "budget_choice": "1", "on_budget": "1"})
    assert on.status_code == 200
    assert client.get(f"/api/accounts/{setup['bank']['aid']}").json()["on_budget"] is True
    food = client.get(f"/accounts/{setup['food']['aid']}/edit").text
    assert "Part of the budget" not in food


def test_the_budget_tab_is_in_the_navigation(client, setup):
    page = client.get("/").text
    assert page.count('href="/budget"') == 2
