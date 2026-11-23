"""/api/views/categories and /api/views/categories/{category_id}: what the finode app's Categories page and a category's
page show for a month, worked out by services/categories_view.py."""

from datetime import date, timedelta

import pytest

from tests.books import leg
from tests.budget.test_budget import account
from tests.guards.test_isolation import B_USER, signed_in_as

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="10000")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    groceries = account(client, root_accounts, "Groceries", "Expenses")
    dining = account(client, root_accounts, "Dining", "Expenses")
    rent = account(client, root_accounts, "Rent", "Expenses")
    travel = account(client, root_accounts, "Travel", "Expenses")
    return {
        "bank": bank,
        "salary": salary,
        "food": food,
        "groceries": groceries,
        "dining": dining,
        "rent": rent,
        "travel": travel,
    }


def entry(client, debit, credit, amount, when):
    response = client.post(
        "/api/transactions/",
        json={"date": when.isoformat(), "postings": [leg(debit, "debit", amount), leg(credit, "credit", amount)]},
    )
    assert response.status_code == 201, response.text


def view(client, path="/api/views/categories", **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_categories_are_ranked_with_their_share(client, books):
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    entry(client, books["dining"], books["bank"], "100", THIS_MONTH)
    entry(client, books["rent"], books["bank"], "600", THIS_MONTH)
    seen = view(client)
    assert (seen["tab"], seen["month"], seen["is_current"], seen["grand"]) == (
        "expense",
        THIS_MONTH.strftime("%Y-%m"),
        True,
        "1000.00",
    )
    assert [(r["name"], r["total"], r["share"]) for r in seen["rows"]] == [
        ("Rent", "600.00", "60%"),
        ("Groceries", "300.00", "30%"),
        ("Dining", "100.00", "10%"),
        ("Food", "0.00", "0%"),
        ("Travel", "0.00", "0%"),
    ]
    page = view(client, f"/api/views/categories/{books['groceries']['id']}")
    assert page["total"] == "300.00" and not {"subs", "group", "own_here", "can_add_child"} & set(page)


def test_every_category_is_listed_even_with_nothing_in_the_month(client, books):
    assert {r["name"] for r in view(client)["rows"]} == {"Food", "Groceries", "Dining", "Rent", "Travel"}


def test_the_earning_tab_and_a_past_month(client, books):
    entry(client, books["bank"], books["salary"], "5000", LAST_MONTH)
    seen = view(client, tab="income", month=LAST_MONTH.strftime("%Y-%m"))
    assert seen["tab"] == "income" and seen["is_current"] is False
    assert [(r["name"], r["total"]) for r in seen["rows"]] == [("Salary", "5000.00")]


def test_a_closed_category_starts_no_entry(client, books):
    assert client.post(f"/api/categories/{books['travel']['id']}/delete").status_code == 200
    seen = client.get(f"/api/views/categories/{books['travel']['id']}")
    assert seen.status_code in (200, 404)
    rent = books["rent"]["id"]
    entry(client, books["rent"], books["bank"], "10", THIS_MONTH)
    assert client.post(f"/api/categories/{rent}/delete").status_code == 200
    assert view(client, f"/api/views/categories/{rent}")["new_transaction_url"] is None


def test_an_entry_on_a_category_page(client, books):
    entry(client, books["rent"], books["bank"], "600", THIS_MONTH)
    [row] = view(client, f"/api/views/categories/{books['rent']['id']}")["entries"]
    assert (row["amount"], row["inflow"], row["negative"], row["balance"]) == ("600.00", False, False, None)


def test_a_bad_month_is_this_month_and_a_stranger_is_not_found(client, books):
    assert view(client, month="13-2026")["month"] == THIS_MONTH.strftime("%Y-%m")
    assert view(client, month="2999-01")["is_current"] is True, "never the future"
    with signed_in_as(B_USER):
        assert client.get(f"/api/views/categories/{books['rent']['id']}").status_code == 404
        assert "Rent" not in client.get("/api/views/categories").text


def form(client, **params):
    return view(client, "/api/views/category-form", **params)


def test_a_category_form(client, books):
    blank = form(client)
    assert (blank["editing"], blank["kind"]) == (False, "spending") and "groups" not in blank
    assert form(client, root="income")["kind"] == "earning"
    food = form(client, category_id=books["food"]["id"])
    assert food["editing"] is True and food["name"] == "Food" and "parent_id" not in food


def test_a_strangers_category_form_is_not_found(client, books):
    with signed_in_as(B_USER):
        assert client.get("/api/views/category-form", params={"category_id": books["food"]["id"]}).status_code == 404


# Ported from test_categories.py (the old Categories pages), step 10.


def test_a_used_category_deleted_stays_in_its_month_leaves_the_pickers_and_comes_back(client, books):
    entry(client, books["groceries"], books["bank"], "300", LAST_MONTH.replace(day=3))
    assert client.post(f"/api/categories/{books['groceries']['id']}/delete").status_code == 200
    assert "Groceries" not in [r["name"] for r in view(client)["rows"]], "not listed where it has nothing"
    last = view(client, month=LAST_MONTH.strftime("%Y-%m"))
    assert "Groceries" in [r["name"] for r in last["rows"]], "still in the month it was used"
    offered = {o["id"] for g in view(client, "/api/views/entry-form")["groups"] for o in g["options"]}
    assert books["groceries"]["id"] not in offered, "the Add screen does not offer it"
    assert client.post(f"/api/categories/{books['groceries']['id']}/reopen").status_code == 200
    assert books["groceries"]["id"] in {
        o["id"] for g in view(client, "/api/views/entry-form")["groups"] for o in g["options"]
    }


def test_a_category_has_no_account_page_and_an_account_no_category_page(client, books):
    assert client.get(f"/api/views/accounts/{books['rent']['id']}").status_code == 404
    assert client.get(f"/api/views/categories/{books['bank']['id']}").status_code == 404


def test_a_category_that_was_spent_in_can_be_deleted_without_emptying_it_first(client, books):
    entry(client, books["rent"], books["bank"], "900", THIS_MONTH)
    assert client.post(f"/api/categories/{books['rent']['id']}/close").status_code == 200, "its balance is spending"
    assert client.post(f"/api/accounts/{books['bank']['id']}/close").status_code == 400, (
        "an account holding money is not"
    )


def test_share_rounding_edges():
    from decimal import Decimal

    from finode.services.categories_view import share as _share

    assert _share(Decimal(0), Decimal(100)) == "0%" and _share(Decimal(0), Decimal(0)) == "0%"
    assert _share(Decimal("0.4"), Decimal(100)) == "<1%" and _share(Decimal(25), Decimal(100)) == "25%"
    assert _share(Decimal(5), Decimal(0)) == "", "no total to take a share of"
