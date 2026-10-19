"""The budget page: reading it, assigning inline, moving money, and switching accounts in."""

import re
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
    assert "Left to spend in" not in page, "that figure is Home's; Budget leads with what is left to assign"
    assert 'class="ready zero budget-hero ready-hero"' in page
    assert "Food" in page and "Rent" in page and THIS_MONTH.strftime("%b %Y") in page, "the pill says which month"
    assert 'href="/budget?month=' in page


def test_an_empty_budget_says_how_to_start(client, root_accounts):
    page = client.get("/budget").text
    assert "No account is part of the budget yet" in page


def test_assigning_inline_returns_the_updated_block(client, setup):
    response = client.post(
        "/budget/assign", data={"category": setup["food"]["aid"], "month": THIS_MONTH.strftime("%Y-%m"), "amount": "300"}
    )
    assert response.status_code == 200 and 'id="budget"' in response.text
    assert "700.00" in response.text
    assert f'value="300.00"' in client.get(f"/budget/category/{setup['food']['aid']}/sheet").text, "the sheet shows what is assigned"
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
    assert (THIS_MONTH - timedelta(days=1)).strftime("%b %Y") in page and THIS_MONTH.strftime("%b %Y") not in page
    assert THIS_MONTH.strftime("%b %Y") in client.get("/budget?month=nonsense").text, "unreadable falls back to now"


def test_overspending_and_overassigning_are_called_out(client, setup):
    assign(client, setup["food"], "1500")
    page = client.get("/budget").text
    assert 'class="ready-warn assigned"' in page and "Over-assigned by" in page
    assert "ready-warn over" not in page, "nothing was spent beyond a category"
    assert "Ready to assign" in page and "0.00" in page


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
    assert f'/budget/category/{setup["food"]["aid"]}/sheet' in page, "a row opens its sheet"
    sheet = client.get(f"/budget/category/{setup['food']['aid']}/sheet").text
    assert 'hx-post="/budget/assign"' in sheet and 'enterkeyhint="done"' in sheet and 'type="submit"' in sheet


def test_categories_are_a_ranked_list_and_a_group_opens_its_own_page(client, root_accounts, setup):
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": setup["food"]["aid"]}).json()
    assign(client, setup["rent"], "500")
    assign(client, groceries, "200")
    page = client.get("/budget").text
    assert 'class="grp"' not in page and "gsum" not in page, "nothing folds"
    assert page.index(">Rent<") < page.index(">Food<"), "biggest budget first"
    assert f'href="/budget/group/{setup["food"]["aid"]}?month=' in page and "Groceries" in page, "Food opens its page; its hint names what is inside"
    assert 'class="r crow catrow"' in page and 'name="amount"' not in page, "no input boxes on the page: assigning happens in the sheet"
    assert 'aria-label="Category"' in page and page.count('class="bar') == 2


def test_a_group_page_lists_its_categories_and_its_figure_opens_its_own_budget(client, root_accounts, setup):
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": setup["food"]["aid"]}).json()
    dining = client.post("/api/accounts/", json={"name": "Dining", "parent_id": setup["food"]["aid"]}).json()
    assign(client, groceries, "200")
    assign(client, dining, "300")
    page = client.get(f"/budget/group/{setup['food']['aid']}").text
    assert page.index("Dining") < page.index("Groceries"), "biggest first"
    assert "Everything else" not in page, "no row for what is not in a category: the group's bar covers it"
    assert f'hx-get="/budget/group/{setup["food"]["aid"]}/sheet?month=' in page and "budget-hero tappable" in page, "the figure area opens the group's budget"
    assert "circ-button" not in page.split('id="budget"', 1)[1], "no pencil"
    assert 'class="cat-bar acct-nav"' in page and 'class="month-pill"' in page and 'class="group-title"' in page and "Left to spend" in page and "Left in Food" not in page
    assert page.index('class="month-pill"') < page.index('class="group-title"'), "the pill is above the name"
    assert "500.00" in page
    assert f'/budget/category/{groceries["aid"]}/sheet?month=' in page and f"group={setup['food']['aid']}" in page
    assert client.get(f"/budget/group/{setup['rent']['aid']}").status_code == 404, "a plain category has no group page"
    assert client.get("/budget/group/00000000-0000-4000-8000-0000000000ff").status_code == 404


def test_assigning_from_a_group_page_returns_that_page_block(client, root_accounts, setup):
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": setup["food"]["aid"]}).json()
    sheet = client.get(f"/budget/category/{groceries['aid']}/sheet?group={setup['food']['aid']}").text
    assert f'name="group" value="{setup["food"]["aid"]}"' in sheet
    response = client.post("/budget/assign", data={"category": groceries["aid"], "amount": "250", "group": setup["food"]["aid"], "sheet": "1"})
    assert response.status_code == 200 and "budget-group" in response.text and "Left to spend" in response.text and "250.00" in response.text


def test_money_can_be_assigned_to_a_group_itself_and_counts_in_its_total(client, root_accounts, setup):
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": setup["food"]["aid"]}).json()
    sheet = client.get(f"/budget/category/{setup['food']['aid']}/sheet")
    assert sheet.status_code == 200 and "Food · everything else" in sheet.text, "a group has a sheet of its own"
    assign(client, groceries, "100")
    client.post("/budget/assign", data={"category": setup["food"]["aid"], "month": THIS_MONTH.strftime("%Y-%m"), "amount": "40"})
    food = line(api_budget(client), "Food")
    assert food["assigned"] == "140.00", "the group's total adds up its own and its categories' money"
    assert 'value="40.00"' in client.get(f"/budget/category/{setup['food']['aid']}/sheet").text


def test_unused_groups_are_tucked_away_once_something_is_in_use_but_plain_categories_stay(client, root_accounts, setup):
    travel = account(client, root_accounts, "Travel", "Expenses")
    client.post("/api/accounts/", json={"name": "Stay", "parent_id": travel["aid"]})
    assert "unused-hidden" not in client.get("/budget").text, "nothing in use yet: everything shows"
    assign(client, setup["food"], "100")
    page = client.get("/budget").text
    assert page.count('class="top unused-hidden"') == 1 and "1 unused group hidden" in page, "the empty Travel group"
    assert 'class="top "' in page and "Rent" in page.split("data-toggle-budget-unused")[0], "Rent is a plain category: it stays"


def test_what_needs_you_is_a_badge_that_opens_a_panel(client, setup):
    last = (THIS_MONTH - timedelta(days=1)).replace(day=1)
    assign(client, setup["food"], "300", last)
    page = client.get("/budget").text
    assert "data-toggle-attn" in page and "Needs you <i>1</i>" in page and "Copy last month's amounts" in page
    assert "things need you" not in page and "thing needs you" not in page, "no separate card any more"


def test_the_sheet_of_a_plain_account_is_not_offered(client, root_accounts, setup):
    assert client.get(f"/budget/category/{setup['bank']['aid']}/sheet").status_code == 404
    assert client.get("/budget/category/00000000-0000-4000-8000-0000000000ff/sheet").status_code == 404


def test_an_error_in_the_sheet_shows_in_the_sheet(client, setup):
    response = client.post("/budget/assign", data={"category": setup["food"]["aid"], "amount": "lots", "sheet": "1"})
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#cat-sheet-error"


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
    assert "Assign what is needed" not in page
    sheet = client.get(f"/budget/category/{setup['rent']['aid']}/sheet").text
    assert f'href="/budget/target?month={THIS_MONTH:%Y-%m}&category={setup["rent"]["aid"]}"' in sheet and "Target and note" in sheet
    form = client.get(f"/budget/target?category={setup['rent']['aid']}")
    assert form.status_code == 200 and "Target for Rent" in form.text and 'name="kind"' in form.text
    saved = client.post("/budget/target", data={"category": setup["rent"]["aid"], "kind": "monthly", "amount": "400"})
    assert saved.headers["HX-Redirect"].startswith("/budget?month=") and "budget-target" in saved.headers["set-cookie"]
    page = client.get("/budget").text
    assert "needs 400.00 more" in page, "the row says what is missing"
    assert "Monthly 400.00" in client.get(f"/budget/category/{setup['rent']['aid']}/sheet").text
    assert "Your targets still need \u20b9400.00" in page and "Assign what is needed" in page


def test_fund_button_assigns_and_the_row_turns_funded(client, setup):
    client.post("/budget/target", data={"category": setup["rent"]["aid"], "kind": "monthly", "amount": "400"})
    response = client.post("/budget/fund", data={"month": THIS_MONTH.strftime("%Y-%m")})
    assert response.status_code == 200 and 'id="budget"' in response.text
    assert "needs 400.00 more" not in response.text and "Assign what is needed" not in response.text
    assert "funded" in client.get(f"/budget/category/{setup['rent']['aid']}/sheet").text
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


def test_the_page_offers_to_copy_last_month_and_does_it(client, setup):
    last = (THIS_MONTH - timedelta(days=1)).replace(day=1)
    assign(client, setup["food"], "300", last)
    page = client.get("/budget").text
    assert "Copy last month's amounts · 300.00" in page
    response = client.post("/budget/copy", data={"month": THIS_MONTH.strftime("%Y-%m")})
    assert response.status_code == 200 and 'id="budget"' in response.text
    assert "Copy last month's amounts" not in response.text
    assert 'value="300.00"' in client.get(f"/budget/category/{setup['food']['aid']}/sheet").text
    again = client.post("/budget/copy", data={})
    assert again.status_code == 400 and again.headers["HX-Retarget"] == "#budget-error"


def test_the_page_says_when_money_is_assigned_to_later_months(client, setup):
    nxt = (THIS_MONTH + timedelta(days=32)).replace(day=1)
    assign(client, setup["food"], "120", nxt)
    assert "\u20b9120.00 is already assigned to later months" in client.get("/budget").text
def test_the_page_lists_cards_and_explains_ready_to_assign(client, root_accounts):
    account(client, root_accounts, "Bank", "Assets", balance="1000")
    food = account(client, root_accounts, "Food", "Expenses")
    assert "Cards to pay" not in client.get("/budget").text, "no card in the budget, no section"
    card = account(client, root_accounts, "Visa", "Liabilities", on_budget=True)
    move(client, card, food, "100")
    page = client.get("/budget").text
    assert "Cards to pay" in page and "Visa" in page
    assert "Charged 100.00 · paid 0.00 this month" in page
    assert "Money in your accounts 1,000.00 − set aside for card bills 100.00" in page
    assert "= ready to assign" in page and "assigned to later months" not in page
    nxt = (THIS_MONTH + timedelta(days=32)).replace(day=1)
    assign(client, food, "50", nxt)
    assert "− assigned to later months 50.00 = ready to assign" in client.get("/budget").text


def test_a_budget_account_with_sub_accounts_is_not_announced_on_the_page(client, setup, root_accounts):
    """It is left out of the sums (only accounts that hold money count) but the page does not say so: nothing to do."""
    deposits = account(client, root_accounts, "Deposits", "Assets")
    client.post("/api/accounts/", json={"name": "FD", "parent_id": deposits, "balance": "10"})
    page = client.get("/budget").text
    assert "Left out because" not in page and "sub-accounts" not in page


def test_one_overspent_category_is_not_a_warning_but_overspending_overall_is(client, setup):
    assign(client, setup["food"], "100")
    assign(client, setup["rent"], "500")
    move(client, setup["bank"], setup["food"], "150")  # Food is 50 over, Rent still has 500: overall there is 450 left
    page = client.get("/budget").text
    assert "ready-warn" not in page, "the category's own bar shows it"
    move(client, setup["bank"], setup["food"], "600")  # now more is spent than was assigned in all
    page = client.get("/budget").text
    assert 'class="ready-warn over"' in page and "Overspent by" in page and "150.00" in page.replace("₹", "")
    assert "ready-warn assigned" not in page, "ready to assign is still positive"
    assign(client, setup["rent"], "5000")  # more than there is
    page = client.get("/budget").text
    assert "ready-warn assigned" in page


def test_no_warning_when_nothing_is_over(client, setup):
    assign(client, setup["food"], "100")
    assert "ready-warn" not in client.get("/budget").text


def test_the_heading_is_a_title_and_a_pill_with_both_arrows(client, setup):
    page = client.get("/budget").text
    assert "<h1>Budget</h1>" in page and 'class="month-pill"' in page
    assert 'title="Previous month"' in page and 'title="Next month"' in page, "the budget can look ahead"
    assert "Needs you" not in page, "nothing needs a decision yet"


def test_the_i_on_budget_shows_the_sum_behind_ready_to_assign(client, setup):
    assign(client, setup["food"], "300")
    page = client.get("/budget").text
    assert 'aria-label="How what is ready to assign is worked out"' in page
    sums = re.findall(r'<p class="calc-row-line([^"]*)"><span>([^<]*)</span><b>([^<]*)</b>', page)
    assert [(c.strip(), label, amount) for c, label, amount in sums] == [
        ("", "In your accounts", "₹1,000.00"),
        ("minus", "Set aside for card bills", "₹0.00"),
        ("minus", "Left in your categories", "₹300.00"),
        ("minus", "Assigned to later months", "₹0.00"),
        ("total", "Ready to assign", "₹700.00"),
    ]


def test_a_groups_budget_starts_at_what_its_categories_add_up_to_and_never_goes_below(client, root_accounts, setup):
    food = setup["food"]["aid"]
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": food}).json()
    dining = client.post("/api/accounts/", json={"name": "Dining", "parent_id": food}).json()
    assign(client, groceries, "200")
    assign(client, dining, "300")
    month = THIS_MONTH.strftime("%Y-%m")
    sheet = client.get(f"/budget/group/{food}/sheet?month={month}").text
    assert 'value="500.00"' in sheet and 'data-min="500.00"' in sheet

    below = client.post(f"/budget/group/{food}/assign", data={"month": month, "amount": "499"})
    assert below.status_code == 400 and "Minimum 500.00" in below.text and below.headers["HX-Retarget"] == "#cat-sheet-error"
    assert line(api_budget(client), "Food")["assigned"] == "500.00", "nothing was saved"

    more = client.post(f"/budget/group/{food}/assign", data={"month": month, "amount": "800"})
    assert more.status_code == 200 and "budget-group" in more.text
    assert line(api_budget(client), "Food")["assigned"] == "800.00" and 'value="800.00"' in client.get(f"/budget/group/{food}/sheet?month={month}").text
    assert line(api_budget(client), "Groceries")["assigned"] == "200.00", "its categories are untouched"
    assert client.post(f"/budget/group/{food}/assign", data={"month": month, "amount": "500"}).status_code == 200, "back to the minimum is fine"
    assert client.get(f"/budget/group/{setup['rent']['aid']}/sheet").status_code == 404, "a plain category has no group budget"
