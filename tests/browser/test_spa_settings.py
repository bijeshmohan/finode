"""The React app's Settings page in a browser (ports of test_settings_page.py), the theme kept in this browser, and
signing out."""

import re

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def row(page: Page, title: str):
    return page.locator("main").get_by_role("button", name=re.compile(f"^{title}"))


def test_saving_the_currency_shows_the_new_one(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    spa_api.post(
        "/transactions/",
        postings=[leg(spa_books["food"], "debit", "40"), leg(spa_books["checking"], "credit", "40")],
    )
    page.goto("/settings")
    expect(row(page, "Currency")).to_contain_text("INR")
    row(page, "Currency").click()
    page.get_by_label("Currency").select_option("USD")
    page.get_by_role("button", name="Save currency").click()
    expect(page.get_by_text("Currency saved")).to_be_visible()
    expect(row(page, "Currency")).to_contain_text("USD")
    page.get_by_role("navigation", name="Tab bar").get_by_role("link", name="Accounts").click()
    expect(page.locator("main")).to_contain_text("USD")
    expect(page.locator("main")).not_to_contain_text("₹")


def test_a_touched_row_is_not_painted_grey(signed_in_spa_page: Page, spa_books):
    """A tap or the start of a scroll leaves :hover on in touch browsers: rows must not turn into a grey rectangle."""
    page = signed_in_spa_page
    page.goto("/settings")
    for target in (row(page, "Currency"), page.locator("main").get_by_role("link", name="Tags")):
        target.hover()
        assert target.evaluate("e => getComputedStyle(e).backgroundColor") in ("rgba(0, 0, 0, 0)", "transparent")


def test_values_sit_beside_the_chevron_and_sign_out_is_a_red_row(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/settings")
    for title in ("Currency", "Appearance"):
        value = row(page, title).locator("span").nth(1).bounding_box()
        chevron = row(page, title).locator("svg").bounding_box()
        assert value and chevron
        assert 0 <= chevron["x"] - (value["x"] + value["width"]) <= 12, (
            f"{title}: the value is right beside the chevron"
        )
    out = page.get_by_role("button", name="Sign out")
    expect(out).to_be_visible()
    title = row(page, "Currency").locator("span").first
    assert out.evaluate("e => getComputedStyle(e).color") != title.evaluate("e => getComputedStyle(e).color")
    box = out.bounding_box()
    assert box and box["width"] > 200, "a full row, not a small pill"


def test_the_theme_is_kept_in_this_browser_and_set_before_the_app_runs(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/settings")
    row(page, "Appearance").click()
    page.get_by_role("group", name="Theme").get_by_role("button", name="Dark").click()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    expect(row(page, "Appearance")).to_contain_text("Dark")
    # With the app's own script kept from loading, only index.html's has run: the page is dark already.
    page.route(re.compile(r"/assets/.*\.js$"), lambda route: route.abort())
    page.reload()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.unroute(re.compile(r"/assets/.*\.js$"))
    page.reload()
    row(page, "Appearance").click()
    page.get_by_role("group", name="Theme").get_by_role("button", name="Match device").click()
    assert page.evaluate("document.documentElement.hasAttribute('data-theme')") is False


def test_signing_out_lands_on_sign_in_and_pages_then_ask_to_sign_in(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/settings")
    page.get_by_role("button", name="Sign out").click()
    page.wait_for_url(re.compile(r"/sign-in"))
    page.goto("/accounts")
    page.wait_for_url(re.compile(r"/sign-in\?next=%2Faccounts"))
