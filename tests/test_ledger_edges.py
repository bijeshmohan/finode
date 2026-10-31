"""Inputs at the edges of what is allowed: nothing may turn into a server error or hide the rest of the books."""

import pytest

from .books import leg, post_account


def post(client, debit, credit, amount, **extra):
    return client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(debit, "debit", amount),
                leg(credit, "credit", amount),
            ],
            **extra,
        },
    )


def test_sums_longer_than_one_amount_can_be_still_show_up(client, root_accounts, account, expense_account):
    """Each amount may have 16 digits before the point; three of them add up to 17, and every page still opens.
    (5 followed by 15 zeros is exact even in SQLite's floating point, which the tests use; Postgres keeps 16 digits.)"""
    for _ in range(3):
        made = post(client, expense_account, account, "5000000000000000.00")
        assert made.status_code == 201, made.text
    for page in (
        "/",
        "/accounts",
        "/categories",
        "/budget",
        f"/accounts/{account['aid']}",
        "/api/accounts/",
        "/api/reports/trial-balance",
        "/api/budget/",
    ):
        assert client.get(page).status_code == 200, page
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    assert client.get(f"/api/accounts/{root_accounts['Expenses']}").json()["balance"] == "15000000000000000.00"


@pytest.mark.parametrize("day", ["1899-12-31", "3000-01-01", "0001-01-01", "9999-12-31"])
def test_a_transaction_outside_the_calendar_finode_works_in_is_refused_with_a_reason(
    client, account, expense_account, day
):
    response = post(client, expense_account, account, "5", date=day)
    assert response.status_code == 422 and "the date must be between 01 Jan 1900 and 31 Dec 2999" in response.text


@pytest.mark.parametrize("day", ["1900-01-01", "2999-12-31"])
def test_the_first_and_last_day_work_everywhere(client, account, expense_account, day):
    assert post(client, expense_account, account, "5", date=day).status_code == 201
    for page in (
        "/",
        "/transactions",
        "/accounts",
        "/budget",
        f"/budget?month={day[:7]}",
        f"/categories?month={day[:7]}",
    ):
        assert client.get(page).status_code == 200, page


@pytest.mark.parametrize("month", ["0001-01", "9999-12", "1899-12", "2200-01", "1900-01", "2999-12"])
def test_odd_months_in_the_address_never_break_a_page(client, expense_account, month):
    for page in ("/budget", "/categories", f"/budget/group/{expense_account['aid']}"):
        assert client.get(f"{page}?month={month}").status_code in (200, 404), (page, month)


def test_the_api_refuses_a_month_it_cannot_work_with(client):
    assert client.get("/api/budget/?month=9999-12-01").status_code == 400
    assert client.get("/api/budget/?month=0001-01-01").status_code == 400
    assert client.get("/api/budget/?month=2026-10-01").status_code == 200


def test_the_ends_of_the_calendar_do_not_move_the_month_arrows_off_it():
    from datetime import date

    from app.routers.web.budget import shift

    assert shift(date(2999, 12, 1), 1) == date(2999, 12, 1)
    assert shift(date(1900, 2, 1), -1) == date(1900, 2, 1)
    assert shift(date(2026, 10, 1), 1) == date(2026, 11, 1) and shift(date(2026, 1, 1), -1) == date(2025, 12, 1)


def test_a_nul_character_is_dropped_instead_of_failing(client, account, expense_account, root_accounts):
    made = post(client, expense_account, account, "5", payee="Caf\x00e", comment="a\x00b")
    assert made.status_code == 201 and made.json()["payee"] == "Cafe" and made.json()["comment"] == "ab"
    refused = post_account(client, {"name": "x\x00y", "parent_id": root_accounts["Expenses"]})
    assert refused.status_code == 422 and "control characters" in refused.text
    assert client.get("/transactions", params={"q": "Caf\x00e"}).status_code == 200
    assert "Cafe" in client.get("/transactions", params={"q": "Caf\x00e"}).text


@pytest.mark.parametrize("name", ["", "   ", "\t", "\u200b", " \u200b\u200d ", "two\nlines", "a:b"])
def test_an_account_name_must_be_visible_and_on_one_line(client, root_accounts, name):
    assert post_account(client, {"name": name, "parent_id": root_accounts["Expenses"]}).status_code == 422


def test_account_names_are_trimmed_and_unique_where_they_sit(client, root_accounts):
    def make(name, parent):
        return post_account(client, {"name": name, "parent_id": parent})

    food = make("  Food  ", root_accounts["Expenses"])
    assert food.status_code == 201 and food.json()["name"] == "Food"
    clash = make("food", root_accounts["Expenses"])
    assert clash.status_code == 400 and "a category called 'Food'" in clash.json()["detail"]
    assert make("Food", root_accounts["Income"]).status_code == 201, "the same name elsewhere is fine"
    sub = make("Food", food.json()["aid"])
    assert sub.status_code == 201, "a subcategory may share its parent's name"

    fun = make("Fun", root_accounts["Expenses"]).json()
    assert client.patch(f"/api/categories/{fun['aid']}", json={"name": "FOOD"}).status_code == 400
    assert client.patch(f"/api/categories/{fun['aid']}", json={"name": "FUN"}).status_code == 200, (
        "its own name, new capitals"
    )
    assert client.patch(f"/api/categories/{food.json()['aid']}", json={"name": "Fun"}).status_code == 400
    moved = client.patch(f"/api/categories/{sub.json()['aid']}", json={"parent_id": None})
    assert moved.status_code == 400 and "a category called" in moved.json()["detail"], (
        "moving it out would clash with Food"
    )


def test_a_payee_is_one_tidy_line_and_a_blank_one_is_none(client, account, expense_account):
    made = post(client, expense_account, account, "5", payee="  Big   Bazaar \n", comment="  keep\nlines  ")
    assert made.json()["payee"] == "Big Bazaar" and made.json()["comment"] == "keep\nlines"
    blank = post(client, expense_account, account, "5", payee="   ", comment=" ")
    assert blank.json()["payee"] is None and blank.json()["comment"] is None


def test_an_account_cannot_be_on_both_sides_of_one_entry(client, account, expense_account, other_account):
    both = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(account, "debit", "10"),
                leg(account, "credit", "10"),
            ]
        },
    )
    assert both.status_code == 400 and "'checking' is on both sides of the entry" in both.json()["detail"]

    mixed = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "100"),
                leg(account, "credit", "80"),
                leg(expense_account, "credit", "20"),
            ]
        },
    )
    assert mixed.status_code == 400 and "'groceries' is on both sides" in mixed.json()["detail"]

    # the same account on several rows of one side is an ordinary split
    split = client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(expense_account, "debit", "60"),
                leg(expense_account, "debit", "40"),
                leg(account, "credit", "100"),
            ]
        },
    )
    assert split.status_code == 201

    # editing only the payee of an entry does not look at the postings again
    assert client.patch(f"/api/transactions/{split.json()['tid']}", json={"payee": "Shop"}).status_code == 200
    bad_edit = client.patch(
        f"/api/transactions/{split.json()['tid']}",
        json={
            "postings": [
                leg(account, "debit", "5"),
                leg(account, "credit", "5"),
            ]
        },
    )
    assert bad_edit.status_code == 400

    web = client.post(
        "/transactions/split",
        data={"account": [account["aid"], account["aid"]], "side": ["credit", "debit"], "amount": ["10", "10"]},
    )
    assert web.status_code == 400 and "on both sides" in web.text
