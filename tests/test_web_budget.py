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


def test_the_inline_amount_also_saves_on_the_return_key(client, setup):
    # iOS shows no decimal-pad return key, but a keyboard's Enter must not reload the page with a GET.
    page = client.get("/budget").text
    assert 'hx-trigger="change, submit"' in page and 'enterkeyhint="done"' in page


def test_every_row_has_the_same_three_cells_so_the_columns_line_up(client, root_accounts, setup):
    client.post("/api/accounts/", json={"name": "Groceries", "parent_id": setup["food"]["aid"]})
    page = client.get("/budget").text
    rows = page.split('<div class="budget-row')[1:]
    assert len(rows) == 3, "a group, its sub-category and a plain category"
    for row in rows:
        assert row.count('<div class="cell">') == 2, row[:200]
        assert row.count('class="cap">Assigned') == 1 and row.count('class="cap">Available') == 1


def test_the_stylesheet_gives_all_rows_and_the_header_the_same_fixed_columns():
    from pathlib import Path

    css = (Path(__file__).parent.parent / "app" / "static" / "style.css").read_text()
    shared = css[css.index(".budget-columns, .budget-row {"):]
    shared = shared[: shared.index("}")]
    assert "grid-template-columns: minmax(0, 1fr) 9rem 9rem" in shared
    assert "auto" not in shared.split("grid-template-columns")[1].split(";")[0], "auto columns size per row and drift"
    assert "max-width: 39.99rem" in css


def test_the_page_explains_last_months_overspending(client, root_accounts):
    from datetime import timedelta

    bank = account(client, root_accounts, "Bank", "Assets")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    last = (THIS_MONTH - timedelta(days=1)).replace(day=1)
    move(client, salary, bank, "1000", on=last.replace(day=2).isoformat())
    assign(client, food, "10", last)
    move(client, bank, food, "30", on=last.replace(day=5).isoformat())
    page = client.get("/budget").text
    assert "was overspent last month" in page and "20.00 overspent last month" in page
    assert "overspent last month" not in client.get(f"/budget?month={last:%Y-%m}").text


def test_rows_offer_a_target_and_show_what_is_missing(client, setup):
    page = client.get("/budget").text
    assert page.count("Set a target") == 2 and "Assign what is needed" not in page
    form = client.get(f"/budget/target?category={setup['rent']['aid']}")
    assert form.status_code == 200 and "Target for Rent" in form.text and 'name="kind"' in form.text
    saved = client.post("/budget/target", data={"category": setup["rent"]["aid"], "kind": "monthly", "amount": "400"})
    assert saved.headers["HX-Redirect"].startswith("/budget?month=") and "budget-target" in saved.headers["set-cookie"]
    page = client.get("/budget").text
    assert "Monthly 400.00" in page and "needs 400.00 more" in page
    assert "Your targets still need 400.00" in page and "Assign what is needed" in page


def test_fund_button_assigns_and_the_row_turns_funded(client, setup):
    client.post("/budget/target", data={"category": setup["rent"]["aid"], "kind": "monthly", "amount": "400"})
    response = client.post("/budget/fund", data={"month": THIS_MONTH.strftime("%Y-%m")})
    assert response.status_code == 200 and 'id="budget"' in response.text
    assert "funded" in response.text and "Assign what is needed" not in response.text
    assert line(api_budget(client), "Rent")["assigned"] == "400.00"
    nothing = client.post("/budget/fund", data={})
    assert nothing.status_code == 400 and nothing.headers["HX-Retarget"] == "#budget-error"


def test_target_form_errors_and_removal(client, setup):
    rent = setup["rent"]["aid"]
    bad = client.post("/budget/target", data={"category": rent, "kind": "by_date", "amount": "50", "target_date": ""})
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#form-error"
    assert client.post("/budget/target", data={"category": rent, "kind": "monthly", "amount": "abc"}).status_code == 400
    ok = client.post("/budget/target", data={"category": rent, "kind": "by_date", "amount": "50", "target_date": THIS_MONTH.strftime("%Y-%m")})
    assert ok.status_code == 200
    page = client.get(f"/budget/target?category={rent}").text
    assert "Remove target" in page and f'value="{THIS_MONTH:%Y-%m}"' in page
    removed = client.post("/budget/target/delete", data={"category": rent})
    assert "budget-target-cleared" in removed.headers["set-cookie"]
    assert client.get(f"/budget/target?category={setup['bank']['aid']}").status_code == 404


def test_the_page_offers_to_add_a_card_and_adding_it_counts_its_spending(client, root_accounts):
    account(client, root_accounts, "Bank", "Assets", balance="1000")
    card = account(client, root_accounts, "Card", "Liabilities")
    food = account(client, root_accounts, "Food", "Expenses")
    move(client, card, food, "75")
    page = client.get("/budget").text
    assert "not part of the budget" in page and "Liabilities:Card" in page and "Add to budget" in page
    response = client.post(f"/budget/accounts/{card['aid']}/include", data={"month": THIS_MONTH.strftime("%Y-%m")})
    assert response.status_code == 200 and 'id="budget"' in response.text
    assert "Add to budget" not in response.text and "\u221275.00" in response.text
    assert client.post(f"/budget/accounts/{food['aid']}/include", data={}).status_code == 400
