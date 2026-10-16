"""The Categories page: where money goes and comes from, for one month; the Accounts page keeps the rest."""

from datetime import date, timedelta

import pytest

from .test_budget import account, move

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="10000")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": food["aid"]}).json()
    dining = client.post("/api/accounts/", json={"name": "Dining", "parent_id": food["aid"]}).json()
    rent = account(client, root_accounts, "Rent", "Expenses")
    travel = account(client, root_accounts, "Travel", "Expenses")
    return {"bank": bank, "salary": salary, "food": food, "groceries": groceries, "dining": dining, "rent": rent, "travel": travel}


def entry(client, debit, credit, amount, when):
    response = client.post("/api/transactions/", json={"date": when.isoformat(), "postings": [
        {"account": debit["aid"], "side": "debit", "amount": amount},
        {"account": credit["aid"], "side": "credit", "amount": amount}]})
    assert response.status_code == 201, response.text


def test_the_accounts_page_has_no_categories_and_the_categories_page_has_no_accounts(client, books):
    accounts = client.get("/accounts").text
    assert "Bank" in accounts and "Groceries" not in accounts and "Salary" not in accounts
    categories = client.get("/categories").text
    assert "Food" in categories and "Rent" in categories and "Bank" not in categories


def test_a_group_adds_up_its_categories_and_the_page_adds_up_the_groups(client, books):
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    entry(client, books["dining"], books["bank"], "200", THIS_MONTH)
    entry(client, books["rent"], books["bank"], "1000", THIS_MONTH)
    page = client.get("/categories").text
    assert "1,500.00" in page, "the month's spending"
    assert '<details class="cgrp"' in page and "500.00" in page, "Food is 500 and folds"
    assert page.count('class="r crow"') >= 3, "two categories inside Food, and Rent"


def test_money_posted_to_a_group_itself_is_its_everything_else_row(client, books):
    entry(client, books["food"], books["bank"], "40", THIS_MONTH)
    entry(client, books["groceries"], books["bank"], "60", THIS_MONTH)
    page = client.get("/categories").text
    assert "Everything else" in page and "100.00" in page


def test_it_is_one_month_at_a_time_and_never_the_future(client, books):
    entry(client, books["rent"], books["bank"], "1000", LAST_MONTH.replace(day=5))
    this = client.get("/categories").text
    assert "1,000.00" not in this
    last = client.get(f"/categories?month={LAST_MONTH:%Y-%m}").text
    assert "1,000.00" in last and "Spent in" in last
    nxt = client.get(f"/categories?month={(THIS_MONTH + timedelta(days=40)):%Y-%m}", follow_redirects=False)
    assert nxt.status_code == 303 and "/categories" in nxt.headers["location"]


def test_income_is_its_own_tab_with_a_plus_free_green_list(client, books):
    entry(client, books["bank"], books["salary"], "5000", THIS_MONTH)
    page = client.get("/categories?tab=income").text
    assert "Earned in" in page and "5,000.00" in page and "Salary" in page and "Rent" not in page
    assert 'aria-pressed="true">Income<' in page


def test_categories_with_nothing_this_month_are_tucked_away_once_something_has_something(client, books):
    assert "unused-hidden" not in client.get("/categories").text, "nothing yet: everything shows"
    entry(client, books["rent"], books["bank"], "1000", THIS_MONTH)
    page = client.get("/categories").text
    assert page.count('class="top unused-hidden"') == 2 and "2 with nothing in" in page


def test_a_category_page_shows_its_month_and_its_transactions(client, books):
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    entry(client, books["groceries"], books["bank"], "70", LAST_MONTH.replace(day=3))
    page = client.get(f"/categories/{books['groceries']['aid']}").text
    assert "300.00" in page and "Add transaction" in page and "/budget" in page
    assert page.count('class="tx"') == 1, "only this month's"
    assert "Add sub-category" not in page, "a sub-category is as deep as it gets"
    assert "Add sub-category" in client.get(f"/categories/{books['food']['aid']}").text


def test_an_account_page_for_a_category_goes_to_the_category_page(client, books):
    response = client.get(f"/accounts/{books['rent']['aid']}", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/categories/{books['rent']['aid']}"
    assert client.get(f"/categories/{books['bank']['aid']}").status_code == 404, "an asset is not a category"


def test_adding_and_deleting_a_category_stay_on_the_categories_side(client, books):
    created = client.post("/accounts", data={"name": "Gifts", "parent_id": books["food"]["aid"]})
    assert created.status_code == 200
    gift = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Gifts")
    assert "Delete category" in client.get(f"/accounts/{gift['aid']}/edit").text
    deleted = client.post(f"/accounts/{gift['aid']}/delete")
    assert deleted.headers["HX-Redirect"] == "/categories"


def test_the_empty_page_invites_the_first_category(client, root_accounts):
    page = client.get("/categories").text
    assert "No expense categories yet" in page and 'href="/categories/new"' in page


def test_the_chips_are_expense_and_income_and_the_old_spelling_still_works(client, books):
    entry(client, books["rent"], books["bank"], "700", THIS_MONTH)
    page = client.get("/categories").text
    assert 'aria-pressed="true">Expense<' in page and ">Income<" in page and ">Spending<" not in page
    old = client.get("/categories?tab=spending").text
    assert 'aria-pressed="true">Expense<' in old and "700.00" in old
