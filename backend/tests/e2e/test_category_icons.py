"""Category icons in a browser: a new category's icon is chosen on its form and shows on Budgets and on Transactions."""

import re
from datetime import date

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def test_new_category_icon_shows_on_budgets_and_transactions(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    page.goto("/categories/new")
    page.get_by_label("Name").fill("Pantry")
    page.get_by_role("button", name="Add category").click()
    expect(page.get_by_role("alert")).to_have_text("Choose an icon")
    page.get_by_role("button", name=re.compile("Choose an icon")).click()
    page.get_by_role("dialog", name="Icon").get_by_role("button", name="shopping cart").click()
    expect(page.get_by_role("button", name=re.compile("shopping cart.*Change"))).to_be_visible()
    expect(page.get_by_role("dialog", name="Icon")).to_be_hidden()
    page.get_by_role("button", name="Add category").click()
    page.wait_for_url(re.compile(r"/categories/[0-9a-f-]{36}$"))

    pantry = next(c for c in api.get("/categories/") if c["name"] == "Pantry")
    assert pantry["icon"] == "shopping-cart"
    api.post(
        "/transactions/",
        date=date.today().isoformat(),
        payee="BigBasket",
        postings=[leg(pantry, "debit", "250"), leg(books["checking"], "credit", "250")],
    )

    page.goto("/budget")
    line = page.get_by_role("button", name=re.compile("^Pantry"))
    expect(line).to_be_visible()
    expect(line.locator("svg")).to_have_count(1)

    page.goto("/transactions")
    entry = page.get_by_role("button", name=re.compile("BigBasket"))
    expect(entry).to_be_visible()
    expect(entry.locator("svg").first).to_be_visible()
