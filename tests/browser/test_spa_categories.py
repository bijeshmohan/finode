"""The React app's Categories page, a category's page and the category form in a browser (ports of
test_categories_page.py and test_under_picker.py; the comparisons with Budgets wait for step 6)."""

import re
from datetime import date

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def spend(api: Api, books, category, amount="300"):
    api.post(
        "/transactions/",
        date=date.today().isoformat(),
        postings=[leg(category, "debit", amount), leg(books["checking"], "credit", amount)],
    )


def row(page: Page, name: str):
    return page.get_by_role("link", name=re.compile(f"^{name}"))


def test_the_tab_bar_has_categories_and_no_transactions(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/")
    bar = page.get_by_role("navigation", name="Tab bar")
    expect(bar.get_by_role("link", name="Categories")).to_be_visible()
    expect(bar.get_by_role("link", name="Transactions")).to_have_count(0)


def test_categories_are_ranked_and_a_category_opens_its_page_with_what_is_inside(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    food = spa_books["food"]
    spa_api.post("/accounts/", name="Delivery", parent_id=food["id"])  # Groceries is a group now
    delivery = next(c for c in spa_api.get("/categories/") if c["name"] == "Delivery")
    spend(spa_api, spa_books, delivery, "120")
    spend(spa_api, spa_books, spa_books["rent"], "900")
    page.goto("/categories")
    expect(row(page, "Rent")).to_be_visible()
    names = page.locator("main a[href^='/categories/']:not([href*='new'])").evaluate_all(
        "els => els.map(e => e.querySelector('span > span').textContent)"
    )
    assert names[:2] == ["Rent", "Groceries"], names  # biggest first
    expect(row(page, "Groceries")).to_contain_text("Delivery")
    expect(row(page, "Groceries")).to_contain_text("12%")
    amount = row(page, "Groceries").locator("span").last
    assert amount.evaluate("e => e.getBoundingClientRect().right") > 340, "amounts at the right edge"
    row(page, "Groceries").click()
    page.wait_for_url(re.compile(rf"/categories/{food['id']}"))
    expect(page.locator("header p").last).to_have_text("₹120.00")
    row(page, "Delivery").click()
    page.wait_for_url(re.compile(rf"/categories/{delivery['id']}"))
    expect(page.get_by_role("heading", level=1, name="Delivery")).to_be_visible()
    expect(page.get_by_role("heading", name="Transactions")).to_be_visible()


def test_the_month_total_and_the_income_tab(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    spend(spa_api, spa_books, spa_books["rent"], "900")
    spa_api.post(
        "/transactions/",
        date=date.today().isoformat(),
        postings=[leg(spa_books["checking"], "debit", "5000"), leg(spa_books["salary"], "credit", "5000")],
    )
    page.goto("/categories")
    expect(page.get_by_text("₹900.00", exact=True)).to_be_visible()
    page.get_by_role("radio", name="Earning").click()
    expect(page.get_by_text("₹5,000.00", exact=True)).to_be_visible()
    expect(row(page, "Salary")).to_be_visible()


def test_every_category_is_listed_even_with_nothing_in_the_month(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    spend(spa_api, spa_books, spa_books["rent"], "900")
    page.goto("/categories")
    expect(row(page, "Groceries")).to_contain_text("Nothing yet")
    expect(page.get_by_role("button", name="Load more")).to_have_count(0)


def test_a_category_opens_its_page_and_adding_a_transaction_comes_back_to_it(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    rent = spa_books["rent"]["id"]
    spend(spa_api, spa_books, spa_books["rent"], "900")
    page.goto("/categories")
    row(page, "Rent").click()
    page.wait_for_url(re.compile(rf"/categories/{rent}"))
    expect(page.locator("header p").last).to_have_text("₹900.00")
    expect(
        page.get_by_role("navigation", name="Tab bar").get_by_role("link", name="New transaction")
    ).to_have_attribute("href", f"/transactions/new?category={rent}&back=/categories/{rent}")
    page.get_by_label("More actions").click()
    expect(page.get_by_role("link", name="See in Budgets")).to_be_visible()


def test_there_is_room_between_the_figure_and_the_first_row(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    spend(spa_api, spa_books, spa_books["rent"], "900")
    page.goto("/categories")
    figure = page.get_by_text("₹900.00", exact=True).bounding_box()
    first = row(page, "Rent").bounding_box()
    assert figure and first
    gap = first["y"] - (figure["y"] + figure["height"])
    assert gap >= 14, f"the list starts {gap}px under the figure"


def test_the_month_pill_sits_in_the_title_row_as_on_transactions(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    spend(spa_api, spa_books, spa_books["rent"], "900")
    spots = {}
    for path in ("/categories", "/transactions"):
        page.goto(path)
        title = page.locator("main h1").first.bounding_box()
        pill = page.get_by_label("Choose a month").locator("xpath=../..").bounding_box()
        assert title and pill
        assert abs((title["y"] + title["height"] / 2) - (pill["y"] + pill["height"] / 2)) < 14, f"{path}: beside"
        spots[path] = round(pill["x"] + pill["width"])
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert len(set(spots.values())) == 1, f"the pill ends at the same edge on every page: {spots}"
    page.goto("/categories")
    chips = page.get_by_role("radiogroup", name="What to show").bounding_box()
    assert chips and chips["width"] > page.viewport_size["width"] - 60, "the switcher spans the page"


def test_the_month_in_the_pill_goes_straight_to_that_month(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/categories")
    month = page.get_by_label("Choose a month")
    assert month.get_attribute("type") == "month" and month.get_attribute("max") == date.today().strftime("%Y-%m")
    month.fill("2026-02")
    page.wait_for_url(re.compile(r"month=2026-02"))
    expect(page.get_by_text("Spent in February")).to_be_visible()


def test_the_head_is_the_same_on_accounts_and_categories(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    spots = {}
    for path, label in (("/accounts", "Net worth"), ("/categories", "Spent so far")):
        page.goto(path)
        title = page.locator("main h1").first.bounding_box()
        hero = page.get_by_text(label, exact=True).bounding_box()
        assert title and hero
        spots[path] = (round(title["y"]), round(hero["height"]))
    assert len(set(spots.values())) == 1, f"the titles line up and the labels match: {spots}"


def test_under_on_the_category_form_can_be_none(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    group = spa_api.post("/categories/", name="Food", kind="spending")
    page.goto(f"/categories/new?parent={group['id']}")
    under = page.get_by_role("button", name=re.compile("^Under"))
    expect(under).to_have_text("Food")
    under.click()
    page.get_by_role("dialog", name="Under").get_by_role("button", name="None (top level)").click()
    expect(under).to_have_text("None (top level)")
    page.get_by_label("Name").fill("Pets")
    page.get_by_role("button", name="Add category").click()
    page.wait_for_url(re.compile(r"/categories/[0-9a-f-]{36}$"))
    pets = next(c for c in spa_api.get("/categories/") if c["name"] == "Pets")
    assert pets["parent_id"] is None
