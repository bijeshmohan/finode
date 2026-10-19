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


def test_the_tab_bar_has_categories_and_no_transactions_(page: Page, books):
    page.goto("/")
    bar = page.locator("nav.tabbar")
    expect(bar.get_by_role("link", name="Categories")).to_be_visible()
    expect(bar.get_by_role("link", name="Transactions")).to_have_count(0)
    expect(page.get_by_role("link", name="Search transactions")).to_have_count(0)


def test_categories_are_ranked_and_a_category_opens_its_page_with_what_is_inside(page: Page, books, api: Api):
    food = tree(api, books)
    delivery = next(a for a in api.get("/accounts/") if a["name"] == "Delivery")
    spend(api, books, delivery, "120")
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    names = page.locator("a.crow .crow-name").all_inner_texts()
    assert names[:2] == ["Rent", "Groceries"], names  # biggest first
    expect(page.locator("a.crow", has_text="Groceries").locator(".crow-sub")).to_have_text("Delivery")
    expect(page.locator("a.crow", has_text="Groceries").locator(".crow-share")).to_have_text("12%")
    assert page.evaluate("document.querySelector('.crow-amt').getBoundingClientRect().right") > 340, "amounts at the right edge"
    page.locator("a.crow", has_text="Groceries").click()
    page.wait_for_url(f"**/categories/{food['aid']}**")
    expect(page.locator(".hero-balance")).to_have_text("₹120.00")
    expect(page.locator("a.crow", has_text="Delivery")).to_be_visible()
    page.locator("a.crow", has_text="Delivery").click()
    page.wait_for_url("**/categories/*")
    expect(page.locator("a.tx").first).to_be_visible()


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
    page.get_by_role("button", name="Load more").click()
    expect(page.locator("a.crow", has_text="Groceries")).to_be_visible()
    expect(page.get_by_role("button", name="Load more")).to_have_count(0)  # it loaded everything: nothing left to load


def test_a_category_opens_its_page_and_adding_a_transaction_comes_back_to_it(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    page.locator("a.crow", has_text="Rent").click()
    page.wait_for_url(f"**/categories/{books['rent']['aid']}**")
    expect(page.locator(".hero-balance")).to_have_text("₹900.00")
    expect(page.get_by_role("link", name="Add transaction")).to_have_attribute("href", f"/transactions/new?account={books['rent']['aid']}&back=/categories/{books['rent']['aid']}")
    page.get_by_label("More actions").click()
    expect(page.get_by_role("link", name="See in the Budget")).to_be_visible()


def test_there_is_room_between_the_figure_and_the_first_row(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    figure = page.locator(".cat-hero .figure").bounding_box()
    first = page.locator("[data-cat-tree]").bounding_box()
    gap = first["y"] - (figure["y"] + figure["height"])
    assert gap >= 14, f"the list starts {gap}px under the figure"


def test_the_month_and_the_kind_share_one_row_above_the_figure(page: Page, books, api: Api):
    spend(api, books, books["rent"], "900")
    page.goto("/categories")
    pill, chips, hero = (page.locator(s).bounding_box() for s in (".month-pill", ".cat-chips", ".cat-hero"))
    assert abs(pill["y"] - chips["y"]) < 14, "side by side"
    assert hero["y"] > pill["y"] + pill["height"] and hero["y"] > chips["y"] + chips["height"] - 2, "the figure is under both"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone"
