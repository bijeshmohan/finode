"""The settings page in a browser: saving a setting shows the new value (the page really reloads)."""

from playwright.sync_api import Page, expect


def test_saving_the_currency_shows_the_new_one(page: Page, books):
    page.goto("/settings")
    expect(page.locator("#currency .setting-value")).to_have_text("INR")
    page.locator("#currency summary").click()
    page.select_option('#currency select[name="currency"]', "USD")
    page.get_by_role("button", name="Save currency").click()
    expect(page.locator("#currency .setting-value")).to_have_text("USD")
    expect(page.locator("#currency")).to_have_attribute("open", "")  # and its row is open on the way back
