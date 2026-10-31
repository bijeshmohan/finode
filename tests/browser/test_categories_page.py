"""The Categories page and the new navigation in a browser."""

import re
from datetime import date

from playwright.sync_api import Page, expect

from .conftest import Api


def tree(api: Api, books):
    food = books["food"]
    api.post(
        "/accounts/", name="Delivery", parent_id=food["aid"]
    )  # a category inside a category: Groceries is a group now
    return food


def spend(api: Api, books, category, amount="300"):
    api.post(
        "/transactions/",
        date=date.today().isoformat(),
        postings=[
            {"account": category["aid"], "side": "debit", "amount": amount},
            {"account": books["checking"]["aid"], "side": "credit", "amount": amount},
        ],
    )


def test_the_tab_bar_has_categories_and_no_transactions_(page: Page, books):
    page.goto("/")
    bar = page.locator("nav.tabbar")
    expect(bar.get_by_role("link", name="Categories")).to_be_visible()
    expect(bar.get_by_role("link", name="Transactions")).to_have_count(0)
    expect(page.get_by_role("link", name="Search transactions")).to_have_count(0)


def test_categories_are_ranked_and_a_category_opens_its_page_with_what_is_inside(page: Page, books, api: Api):
    food = tree(api, books)
    delivery = next(c for c in api.get("/categories/") if c["name"] == "Delivery") | {}
    delivery["aid"] = delivery["bcid"]
    spend(api, books, delivery, "120")
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    names = page.locator("a.crow .crow-name").all_inner_texts()
    assert names[:2] == ["Rent", "Groceries"], names  # biggest first
    expect(page.locator("a.crow", has_text="Groceries").locator(".crow-sub")).to_contain_text("Delivery")
    expect(page.locator("a.crow", has_text="Groceries").locator(".crow-sub")).to_contain_text("12%")
    assert page.evaluate("document.querySelector('.crow-amt').getBoundingClientRect().right") > 340, (
        "amounts at the right edge"
    )
    page.locator("a.crow", has_text="Groceries").click()
    page.wait_for_url(f"**/categories/{food['aid']}**")
    expect(page.locator(".hero-balance")).to_have_text("₹120.00")
    expect(page.locator("a.crow", has_text="Delivery")).to_be_visible()
    page.locator("a.crow", has_text="Delivery").click()
    page.wait_for_url("**/categories/*")
    expect(page.locator("a.tx").first).to_be_visible()


def test_the_month_total_and_the_income_tab(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    api.post(
        "/transactions/",
        date=date.today().isoformat(),
        postings=[
            {"account": books["checking"]["aid"], "side": "debit", "amount": "5000"},
            {"account": books["salary"]["aid"], "side": "credit", "amount": "5000"},
        ],
    )
    page.goto("/categories")
    expect(page.locator(".cat-hero .figure")).to_have_text("₹900.00")
    page.get_by_role("link", name="Earning").click()
    expect(page.locator(".cat-hero .figure")).to_have_text("₹5,000.00")
    expect(page.locator("a.crow", has_text="Salary")).to_be_visible()


def test_every_category_is_listed_even_with_nothing_in_the_month(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    expect(page.locator("a.crow", has_text="Groceries")).to_be_visible()
    expect(page.get_by_role("button", name="Load more")).to_have_count(0)


def test_a_category_opens_its_page_and_adding_a_transaction_comes_back_to_it(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    page.locator("a.crow", has_text="Rent").click()
    page.wait_for_url(f"**/categories/{books['rent']['aid']}**")
    expect(page.locator(".hero-balance")).to_have_text("₹900.00")
    expect(page.get_by_role("link", name="Add transaction")).to_have_attribute(
        "href", f"/transactions/new?category={books['rent']['aid']}&back=/categories/{books['rent']['aid']}"
    )
    page.get_by_label("More actions").click()
    expect(page.get_by_role("link", name="See in Budgets")).to_be_visible()


def test_there_is_room_between_the_figure_and_the_first_row(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    figure = page.locator(".cat-hero .figure").bounding_box()
    first = page.locator("[data-cat-tree]").bounding_box()
    gap = first["y"] - (figure["y"] + figure["height"])
    assert gap >= 14, f"the list starts {gap}px under the figure"


def test_the_month_pill_sits_in_the_title_row_as_on_budget_and_transactions(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    spots = {}
    for path in ("/budget", "/categories", "/transactions"):
        page.goto(path)
        title, pill = (page.locator(s).first.bounding_box() for s in (".page-head h1", ".page-head .month-pill"))
        assert abs((title["y"] + title["height"] / 2) - (pill["y"] + pill["height"] / 2)) < 14, (
            f"{path}: pill beside the title"
        )
        spots[path] = round(pill["x"] + pill["width"])
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
            "no sideways scrolling on a phone"
        )
    assert len(set(spots.values())) == 1, f"the pill ends at the same edge on every page: {spots}"
    page.goto("/categories")
    chips, hero = (page.locator(s).first.bounding_box() for s in (".cat-chips", ".cat-hero"))
    assert page.locator(".cat-bar .head-icons").count() == 0, "no icons beside the switcher"
    assert chips["width"] > page.viewport_size["width"] - 60, "the switcher spans the page"
    assert hero["y"] > chips["y"] + chips["height"] - 2


def test_the_month_in_the_pill_is_a_picker_that_goes_straight_to_that_month(page: Page, books):
    page.goto("/categories")
    pill = page.locator(".month-pill")
    arrows = pill.locator("a.mp-arrow")
    name = pill.locator(".month-pill-name").bounding_box()
    previous = arrows.first.bounding_box()
    assert previous["x"] + previous["width"] <= name["x"], "the back arrow is before the month"
    month = pill.locator(".month-input")
    assert month.get_attribute("type") == "month" and month.get_attribute("max") == date.today().strftime("%Y-%m")
    box = month.bounding_box()
    assert box["width"] >= name["width"] and box["height"] >= name["height"], "the picker covers the month's name"
    month.evaluate("(el) => { el.value = '2026-02'; el.dispatchEvent(new Event('change', {bubbles: true})); }")
    page.wait_for_url(re.compile(r"month=2026-02"))
    expect(page.locator(".month-pill-name")).to_have_text("Feb 2026")
    month = page.locator(".month-input")
    month.evaluate("(el) => { el.value = '2999-01'; el.dispatchEvent(new Event('change', {bubbles: true})); }")
    page.wait_for_timeout(300)
    assert "month=2026-02" in page.url, "a month the page never shows is not taken"


def test_accounts_and_categories_share_the_same_heights(page: Page, books):
    spots = {}
    for path in ("/accounts", "/categories"):
        page.goto(path)
        title, chips, hero = (
            page.locator(s).first.bounding_box() for s in (".page-head h1", ".cat-chips", ".cat-hero")
        )
        assert page.locator(".cat-bar .head-icons").count() == 0, f"{path}: nothing beside the switcher"
        spots[path] = (round(title["y"]), round(chips["y"]), round(chips["width"]), round(hero["y"]))
    assert spots["/accounts"] == spots["/categories"], f"title, full-width switcher and figure line up: {spots}"


def test_the_head_is_the_same_on_accounts_categories_and_budgets(page: Page, books):
    spots = {}
    for path in ("/accounts", "/categories", "/budget"):
        page.goto(path)
        title, chips, label, figure = (
            page.locator(s).first.bounding_box()
            for s in (".page-head h1", ".cat-chips", ".ready-hero .hero-top", ".ready-hero .figure")
        )
        spots[path] = (
            round(title["y"]),
            round(chips["y"]),
            round(label["y"]),
            round(figure["y"]),
            round(figure["height"]),
        )
        expect(page.locator(".ready-hero .hero-top .muted").first).to_be_visible()
    assert len(set(spots.values())) == 1, f"title, switcher, label and figure line up on all three pages: {spots}"
