"""/api/views/categories and /api/views/categories/{category_id}: what the finode app's Categories page and a category's
page show for a month, worked out by services/categories_view.py."""

from datetime import date, timedelta

import pytest

from .books import leg, post_account
from .test_budget import account
from .test_isolation import B_USER, signed_in_as

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="10000")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    groceries = post_account(client, {"name": "Groceries", "parent_id": food["id"]}).json()
    dining = post_account(client, {"name": "Dining", "parent_id": food["id"]}).json()
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


def test_categories_are_ranked_with_what_is_inside_and_their_share(client, books):
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
    assert [(r["name"], r["total"], r["share"], r["hint"]) for r in seen["rows"]] == [
        ("Rent", "600.00", "60%", ""),
        ("Food", "400.00", "40%", "Groceries · Dining"),
        ("Travel", "0.00", "0%", ""),
    ]


def test_every_category_is_listed_even_with_nothing_in_the_month(client, books):
    assert {r["name"] for r in view(client)["rows"]} == {"Food", "Rent", "Travel"}


def test_the_earning_tab_and_a_past_month(client, books):
    entry(client, books["bank"], books["salary"], "5000", LAST_MONTH)
    seen = view(client, tab="income", month=LAST_MONTH.strftime("%Y-%m"))
    assert seen["tab"] == "income" and seen["is_current"] is False
    assert [(r["name"], r["total"]) for r in seen["rows"]] == [("Salary", "5000.00")]


def test_a_groups_page(client, books):
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    entry(client, books["food"], books["bank"], "50", THIS_MONTH)
    seen = view(client, f"/api/views/categories/{books['food']['id']}")
    assert (seen["name"], seen["kind"], seen["total"], seen["own_here"]) == ("Food", "spending", "350.00", "50.00")
    assert [(s["name"], s["total"]) for s in seen["subs"]] == [("Groceries", "300.00"), ("Dining", "0.00")]
    assert [r["amount"] for r in seen["entries"]] == ["50.00"], "only what was labelled with the group itself"
    assert seen["can_add_child"] is True and seen["can_delete"] is True and seen["group"] is None
    food = books["food"]["id"]
    assert seen["new_transaction_url"] == f"/transactions/new?category={food}&back=/categories/{food}"
    plain = view(client, f"/api/views/categories/{books['dining']['id']}")
    assert (
        plain["subs"] == []
        and plain["own_here"] == "0.00"
        and plain["group"]
        == {
            "id": books["food"]["id"],
            "name": "Food",
        }
    )


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
    assert (blank["editing"], blank["kind"], blank["parent_id"]) == (False, "spending", None)
    assert [g["name"] for g in blank["groups"]] == ["Food", "Rent", "Travel"]
    assert form(client, root="income")["kind"] == "earning"
    inside = form(client, parent=books["food"]["id"])
    assert (inside["kind"], inside["parent_id"]) == ("spending", books["food"]["id"])
    group = form(client, category_id=books["food"]["id"])
    assert group["editing"] is True and group["name"] == "Food" and group["groups"] == [], "a group stays a group"
    dining = form(client, category_id=books["dining"]["id"])
    assert dining["parent_id"] == books["food"]["id"] and "Dining" not in [g["name"] for g in dining["groups"]]


def test_a_strangers_category_form_is_not_found(client, books):
    with signed_in_as(B_USER):
        assert client.get("/api/views/category-form", params={"parent": books["food"]["id"]}).status_code == 404
        assert client.get("/api/views/category-form", params={"category_id": books["food"]["id"]}).status_code == 404


# Ported from test_categories.py (the old Categories pages), step 10.


def test_the_hint_names_the_three_biggest_and_counts_the_rest(client, books):
    for name, amount in (("A1", "50"), ("A2", "40"), ("A3", "30"), ("A4", "20")):
        made = post_account(client, {"name": name, "parent_id": books["travel"]["id"]}).json()
        entry(client, made, books["bank"], amount, THIS_MONTH)
    first = view(client)["rows"][0]
    assert (first["name"], first["hint"], first["share"], first["total"]) == (
        "Travel",
        "A1 · A2 · A3 · +1",
        "100%",
        "140.00",
    )


def test_a_closed_subcategory_leaves_its_group(client, books):
    entry(client, books["groceries"], books["bank"], "300", THIS_MONTH)
    assert client.post(f"/api/categories/{books['dining']['id']}/close").status_code == 200
    assert [s["name"] for s in view(client, f"/api/views/categories/{books['food']['id']}")["subs"]] == ["Groceries"]
    assert view(client)["rows"][0]["hint"] == "Groceries"


def test_a_used_category_deleted_stays_in_its_month_leaves_the_pickers_and_comes_back(client, books):
    entry(client, books["groceries"], books["bank"], "300", LAST_MONTH.replace(day=3))
    assert client.post(f"/api/categories/{books['groceries']['id']}/delete").status_code == 200
    this = view(client, f"/api/views/categories/{books['food']['id']}")
    assert "Groceries" not in [s["name"] for s in this["subs"]], "not listed where it has nothing"
    last = view(client, f"/api/views/categories/{books['food']['id']}", month=LAST_MONTH.strftime("%Y-%m"))
    assert "Groceries" in [s["name"] for s in last["subs"]], "still in the month it was used"
    offered = {o["id"] for g in view(client, "/api/views/entry-form")["groups"] for o in g["options"]}
    assert books["groceries"]["id"] not in offered, "the Add screen does not offer it"
    assert client.post(f"/api/categories/{books['groceries']['id']}/reopen").status_code == 200
    assert books["groceries"]["id"] in {
        o["id"] for g in view(client, "/api/views/entry-form")["groups"] for o in g["options"]
    }


def test_deleting_a_group_takes_its_subcategories_along(client, books):
    assert client.post(f"/api/categories/{books['food']['id']}/delete").status_code == 200
    closed = {c["name"]: c["closed_on"] for c in client.get("/api/categories/", params={"include_closed": True}).json()}
    assert closed["Food"] and closed["Groceries"] and closed["Dining"]
    assert "Food" not in [r["name"] for r in view(client)["rows"]]


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

    from app.services.categories_view import share as _share

    assert _share(Decimal(0), Decimal(100)) == "0%" and _share(Decimal(0), Decimal(0)) == "0%"
    assert _share(Decimal("0.4"), Decimal(100)) == "<1%" and _share(Decimal(25), Decimal(100)) == "25%"
    assert _share(Decimal(5), Decimal(0)) == "", "no total to take a share of"
