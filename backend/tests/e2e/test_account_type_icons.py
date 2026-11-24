"""Account type icons in a browser: the Accounts page's headings (once, not again on each row under them), the new
account form's kinds, and a card payment's row on Transactions, which leads with the credit card it went into."""

import re
from datetime import date

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def test_account_type_icons(signed_in_page: Page, api: Api):
    page = signed_in_page
    bank = api.post("/accounts/", name="HDFC", type="assets.bank", balance="5000")
    card = api.post("/accounts/", name="Amex", type="liabilities.cards")
    api.post(
        "/transactions/",
        date=date.today().isoformat(),
        payee="Card bill",
        postings=[leg(card, "debit", "300"), leg(bank, "credit", "300")],
    )

    page.goto("/accounts")
    heading = page.get_by_role("heading", name="Credit Card", level=2)
    expect(heading.locator("xpath=..").locator("svg[data-icon='credit-card']")).to_be_visible()
    expect(page.get_by_role("link", name=re.compile("^HDFC")).locator("svg[data-icon]")).to_have_count(0)

    page.goto("/accounts/new")
    kinds = page.get_by_role("radiogroup", name="Kind of account")
    expect(kinds.locator("svg[data-icon]")).to_have_count(4)
    box = kinds.bounding_box()
    assert box and box["width"] <= page.viewport_size["width"], "the four kinds fit across the screen"

    page.goto("/transactions")
    row = page.get_by_role("button", name=re.compile("Card bill"))
    expect(row.locator("svg[data-icon='credit-card']")).to_be_visible()
