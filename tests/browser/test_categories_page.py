"""The Categories page and the new navigation in a browser."""

from datetime import date

from playwright.sync_api import Page, expect

from .conftest import Api


def tree(api: Api, books):
    food = books["food"]
    api.post("/accounts/", name="Delivery", parent_id=food["aid"])  # a category inside a category: Groceries is a group now
    return food


def spend(api: Api, books, category, amount="300"):
    api.post("/transactions/", date=date.today().isoformat(), postings=[
        {"account": category["aid"], "side": "debit", "amount": amount},
        {"account": books["checking"]["aid"], "side": "credit", "amount": amount}])


def test_the_tab_bar_has_categories_and_no_transactions_and_search_leads_to_the_list(page: Page, books):
    page.goto("/")
    bar = page.locator("nav.tabbar")
    expect(bar.get_by_role("link", name="Categories")).to_be_visible()
    expect(bar.get_by_role("link", name="Transactions")).to_have_count(0)
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("link", name="Search transactions").click()
    page.wait_for_url("**/transactions?focus=search")
    expect(page.locator('.search-pill input[name="q"]')).to_be_focused()  # on a computer; a phone shows the pill, ready to tap


def test_a_group_folds_and_is_remembered(page: Page, books, api: Api):
    food = tree(api, books)
    spend(api, books, books["food"], "500")
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    group = page.locator("details.cgrp", has_text="Groceries").first
    expect(page.locator("a.crow", has_text="Delivery")).to_be_hidden()
    group.locator("summary").click()
    expect(page.locator("a.crow", has_text="Delivery")).to_be_visible()
    page.reload()
    expect(page.locator("a.crow", has_text="Delivery")).to_be_visible()  # remembered
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_month_total_and_the_income_tab(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    api.post("/transactions/", date=date.today().isoformat(), postings=[
        {"account": books["checking"]["aid"], "side": "debit", "amount": "5000"},
        {"account": books["salary"]["aid"], "side": "credit", "amount": "5000"}])
    page.goto("/categories")
    expect(page.locator(".cat-hero .figure")).to_have_text("₹900.00")
    page.get_by_role("link", name="Income").click()
    expect(page.locator(".cat-hero .figure")).to_have_text("₹5,000.00")
    expect(page.locator("a.crow", has_text="Salary")).to_be_visible()


def test_quiet_categories_hide_behind_a_link(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    expect(page.locator("a.crow", has_text="Groceries")).to_be_hidden()
    page.get_by_role("button", name="with nothing in").click()
    expect(page.locator("a.crow", has_text="Groceries")).to_be_visible()


def test_a_category_opens_its_page_and_adding_a_transaction_comes_back_to_it(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    page.locator("a.crow", has_text="Rent").click()
    page.wait_for_url(f"**/categories/{books['rent']['aid']}**")
    expect(page.locator(".hero-balance")).to_have_text("₹900.00")
    expect(page.get_by_role("link", name="Add transaction")).to_have_attribute("href", f"/transactions/new?account={books['rent']['aid']}&back=/categories/{books['rent']['aid']}")
    page.get_by_label("More actions").click()
    expect(page.get_by_role("link", name="See in the Budget")).to_be_visible()


def test_there_is_room_between_the_chips_and_the_first_row(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    chips = page.locator(".cat-chips").bounding_box()
    first = page.locator("[data-cat-tree]").bounding_box()
    gap = first["y"] - (chips["y"] + chips["height"])
    assert gap >= 14, f"the list starts {gap}px under the chips"
