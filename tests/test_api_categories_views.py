"""/api/views/categories and /api/views/categories/{category_id}: what the finode app's Categories page and a category's
page show for a month, worked out as the web pages work it out (services/categories_view.py)."""

from .test_categories import LAST_MONTH, THIS_MONTH, books, entry  # noqa: F401  # books is a fixture
from .test_isolation import B_USER, signed_in_as


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
