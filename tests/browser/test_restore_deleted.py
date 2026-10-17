"""Restoring a deleted entry from the Recently deleted page."""

from playwright.sync_api import Page, expect

from .conftest import Api


def test_restore_puts_the_entry_back_and_it_leaves_the_list(page: Page, books, api: Api):
    entry = api.post("/transactions/", payee="Lunch", postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "120"},
        {"account": books["checking"]["aid"], "side": "credit", "amount": "120"},
    ])
    page.goto("/transactions")
    page.get_by_role("link", name="Recently deleted").click()
    expect(page.get_by_text("Nothing deleted")).to_be_visible()
    api.delete(f"/transactions/{entry['tid']}")
    page.reload()
    expect(page.locator(".del-row", has_text="Lunch")).to_be_visible()
    page.get_by_role("button", name="Restore").click()
    expect(page.get_by_text("Transaction restored")).to_be_visible()
    expect(page.get_by_text("Nothing deleted")).to_be_visible()
    page.goto("/transactions")
    expect(page.locator("a.tx", has_text="Lunch")).to_be_visible()
