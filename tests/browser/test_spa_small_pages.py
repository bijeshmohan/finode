"""The React app's to-do bell, Coming up and Tags pages in a browser (ports of test_todo_bell.py, test_coming_up.py and the
Tags-page tests of test_tags.py), with the web pages' measures (style.css) held to."""

import calendar
import re
from datetime import timedelta

import pytest
from playwright.sync_api import Page, expect

from app.clock import local_today

from ..books import leg
from .conftest import Api


def bell(page: Page):
    return page.get_by_role("banner").get_by_role("button", name="To do")


def todo_sheet(page: Page):
    return page.get_by_role("dialog", name="To do")


def loan_payment(api: Api, books: dict) -> dict:
    loan = api.post("/accounts/", name="Home loan", parent_id=books["roots"]["Liabilities"], on_budget=False)
    emi = api.post("/accounts/", name="EMI", parent_id=books["roots"]["Expenses"])
    api.post(
        "/transactions/",
        payee="EMI payment",
        postings=[leg(loan, "debit", "500"), leg(books["checking"], "credit", "500")],
    )
    return emi


# ---- the bell ---------------------------------------------------------------------------------------------------


def test_the_bell_has_no_count_when_nothing_needs_you(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/")
    expect(bell(page)).to_be_visible()
    expect(bell(page)).to_have_text("")
    bell(page).click()
    expect(todo_sheet(page)).to_contain_text("Nothing needs you.")


def test_a_payment_with_no_category_is_fixed_from_the_sheet_and_the_count_follows(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    emi = loan_payment(spa_api, spa_books)
    page.goto("/accounts")
    expect(bell(page)).to_have_text("1")
    bell(page).click()
    sheet = todo_sheet(page)
    expect(sheet).to_contain_text("1 payment has no category")
    sheet.get_by_label("Category for EMI payment").select_option(emi["id"])
    expect(sheet).to_contain_text("Nothing needs you.")
    expect(bell(page)).to_have_text("")
    entry = next(t for t in spa_api.get("/transactions/") if t["payee"] == "EMI payment")
    assert emi["id"] in {p["category_id"] for p in entry["postings"]}


def test_an_account_left_out_is_added_from_the_sheet(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    card = spa_api.post("/accounts/", name="Old card", parent_id=spa_books["roots"]["Liabilities"], on_budget=False)
    spa_api.post("/transactions/", postings=[leg(spa_books["food"], "debit", "75"), leg(card, "credit", "75")])
    page.goto("/")
    bell(page).click()
    sheet = todo_sheet(page)
    expect(sheet).to_contain_text("Liabilities:Old card is not in the budget")
    sheet.get_by_role("button", name="Add to budget").click()
    expect(sheet).to_contain_text("Nothing needs you.")
    assert spa_api.get(f"/accounts/{card['id']}")["on_budget"] is True


def test_a_bill_due_soon_is_in_the_bell_and_pay_bill_opens_the_form(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    today = local_today()
    statement = today - timedelta(days=10)
    card = spa_api.post(
        "/accounts/",
        name="Amex",
        parent_id=spa_books["roots"]["Liabilities"],
        statement_day=statement.day,
        due_day=(today + timedelta(days=2)).day,
        on_budget=True,  # so its spending (this month from the 16th on) is no "left out" to-do of its own
    )
    spa_api.post(
        "/transactions/",
        date=str(statement - timedelta(days=5)),
        postings=[leg(spa_books["food"], "debit", "300"), leg(card, "credit", "300")],
    )
    page.goto("/")
    expect(bell(page)).to_have_text("1")
    bell(page).click()
    sheet = todo_sheet(page)
    expect(sheet).to_contain_text("Amex bill is due in 2 days")
    sheet.get_by_role("link", name="Pay bill").click()
    page.wait_for_url(re.compile(rf"/transactions/new\?pay={card['id']}&amount=300\.00"))
    expect(todo_sheet(page)).to_have_count(0)


def test_the_bell_sits_where_the_web_page_puts_it(signed_in_spa_page: Page, spa_api: Api, spa_books):
    """style.css: the badge at the bell's top right; in the sidebar the bell sits at the foot with Settings."""
    page = signed_in_spa_page
    loan_payment(spa_api, spa_books)
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto("/")
    expect(bell(page)).to_have_text("1")
    button, badge = bell(page).bounding_box(), bell(page).locator("span").bounding_box()
    settings = page.get_by_role("banner").get_by_role("link", name="Settings").bounding_box()
    assert button and badge and settings
    assert badge["x"] + badge["width"] > button["x"] + button["width"] / 2 and badge["y"] < button["y"] + 10
    assert button["x"] + button["width"] <= settings["x"], "the bell comes before Settings"
    page.set_viewport_size({"width": 1280, "height": 800})
    side = page.get_by_role("navigation", name="Sidebar")
    todo = side.get_by_role("button", name=re.compile("To do")).bounding_box()
    gear = side.get_by_role("link", name="Settings").bounding_box()
    people = side.get_by_role("link", name="People").bounding_box()
    assert todo and gear and people
    assert people["y"] + 100 < todo["y"] < gear["y"], "at the foot, above Settings"


# ---- Coming up --------------------------------------------------------------------------------------------------


@pytest.fixture
def ahead(spa_books, spa_api: Api):
    """Two payments later this month: an entry and, from the rule's own start, an occurrence. Skipped near the month's end."""
    today = local_today()
    last = calendar.monthrange(today.year, today.month)[1]
    if today.day >= last - 1:
        pytest.skip("needs two days left in the month")
    spa_api.post(
        "/transactions/",
        payee="Cab",
        date=str(today + timedelta(days=1)),
        postings=[leg(spa_books["food"], "debit", "70"), leg(spa_books["checking"], "credit", "70")],
    )
    spa_api.post(
        "/recurring/",
        payee="Landlord",
        from_account_id=spa_books["checking"]["id"],
        to_account_id=spa_books["roots"]["Expenses"],
        category_id=spa_books["rent"]["id"],
        amount="1500",
        frequency="monthly",
        start_date=str(today + timedelta(days=2)),
    )


def test_coming_up_opens_from_the_sum_and_lists_what_is_ahead(signed_in_spa_page: Page, spa_books, ahead):
    page = signed_in_spa_page
    page.goto("/budget")
    page.get_by_label("How what is ready to assign is worked out").click()
    note = page.get_by_role("link", name=re.compile("2 payments coming up by"))
    expect(note).to_contain_text("1,570.00")
    note.click()
    page.wait_for_url("**/budget/coming-up")
    expect(page.locator("main h1")).to_have_text("Coming up")
    expect(page.get_by_test_id("coming-figure")).to_have_text("₹1,570.00")
    cab = page.locator("main").get_by_role("link", name=re.compile("^Cab"))
    expect(cab).to_be_visible()
    landlord = page.locator("main").get_by_role("link", name=re.compile("^Landlord"))
    expect(landlord).to_contain_text("Repeats")
    cab.click()
    page.wait_for_url(re.compile(r"/transactions/.+/edit\?back=/budget/coming-up"))


def test_nothing_is_said_when_nothing_is_coming_up(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/budget/coming-up")
    expect(page.locator("main")).to_contain_text("Nothing is coming up before")
    page.goto("/budget")
    page.get_by_label("How what is ready to assign is worked out").click()
    expect(page.get_by_role("region", name="How this is worked out")).to_be_visible()
    expect(page.get_by_role("link", name=re.compile("coming up by"))).to_have_count(0)


# ---- Tags -------------------------------------------------------------------------------------------------------


def tagged(api: Api, books: dict, payee: str, tag: str):
    return api.post(
        "/transactions/",
        payee=payee,
        tags=[tag],
        postings=[leg(books["food"], "debit", "100"), leg(books["checking"], "credit", "100")],
    )


def tag_row(page: Page, name: str):
    return page.locator("main").get_by_role("button", name=re.compile(f"^#{name}"))


def test_the_tags_page_renames_merges_and_deletes(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    tagged(spa_api, spa_books, "A", "alpha")
    tagged(spa_api, spa_books, "B", "beta")
    page.goto("/tags")
    expect(tag_row(page, "")).to_have_count(2)
    tag_row(page, "alpha").click()
    sheet = page.get_by_role("dialog", name="#alpha")
    expect(sheet.get_by_role("link", name="View entries")).to_be_visible()
    sheet.get_by_role("button", name="Rename").click()
    sheet.get_by_label("New name").fill("not valid")
    sheet.get_by_role("button", name="Rename").last.click()
    expect(sheet.get_by_role("alert")).to_contain_text("cannot be a tag")
    sheet.get_by_label("New name").fill("Holiday")
    sheet.get_by_role("button", name="Rename").last.click()
    expect(sheet).to_have_count(0)
    expect(tag_row(page, "holiday")).to_be_visible()
    tag_row(page, "holiday").click()
    sheet = page.get_by_role("dialog", name="#holiday")
    sheet.get_by_role("button", name="Merge into…").click()
    sheet.get_by_label("Merge into").select_option("beta")
    sheet.get_by_role("button", name="Merge", exact=True).click()
    expect(tag_row(page, "")).to_have_count(1)
    page.once("dialog", lambda dialog: dialog.accept())  # the confirmation
    tag_row(page, "beta").click()
    page.get_by_role("dialog", name="#beta").get_by_role("button", name="Delete tag").click()
    expect(page.get_by_text("No tags yet")).to_be_visible()
    assert spa_api.get("/tags/") == []


def test_view_entries_opens_the_list_filtered_by_the_tag(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    tagged(spa_api, spa_books, "Beach shack", "goa")
    tagged(spa_api, spa_books, "Corner shop", "home")
    page.goto("/tags")
    tag_row(page, "goa").click()
    page.get_by_role("dialog", name="#goa").get_by_role("link", name="View entries").click()
    page.wait_for_url(re.compile(r"/transactions\?month=\d{4}-\d{2}&tag=goa"))
    expect(page.locator("main")).to_contain_text("Beach shack")
    expect(page.locator("main")).not_to_contain_text("Corner shop")


def test_the_tags_page_rows_are_plain_rows_inside_one_tile(signed_in_spa_page: Page, spa_api: Api, spa_books):
    """As the web page: one full-width row each, 52px high, no button look, the count at the right."""
    page = signed_in_spa_page
    tagged(spa_api, spa_books, "A", "alpha")
    tagged(spa_api, spa_books, "B", "beta")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/tags")
    rows = tag_row(page, "")
    expect(rows).to_have_count(2)
    first, second = rows.nth(0).bounding_box(), rows.nth(1).bounding_box()
    assert first and second and first["width"] > 300 and second["y"] >= first["y"] + first["height"]
    assert round(first["height"]) >= 52
    assert rows.nth(0).evaluate("e => getComputedStyle(e).backgroundColor") == "rgba(0, 0, 0, 0)"
    count = rows.nth(0).locator("span").last.bounding_box()
    assert count and count["x"] + count["width"] > first["x"] + first["width"] - 20, "the count sits at the right"
    tile = rows.nth(0).locator("xpath=..").bounding_box()
    assert tile and abs(tile["x"] - 16) <= 4, "the tile keeps the page's gutter"
