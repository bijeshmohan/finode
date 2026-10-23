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


def test_restoring_a_deleted_category_opens_it_again(page: Page, books, api: Api):
    snack = api.post("/accounts/", name="Snacks", parent_id=books["roots"]["Expenses"])
    api.delete(f"/accounts/{snack['aid']}")
    page.goto("/settings")
    page.get_by_role("link", name="Recently deleted").click()
    page.locator(".chips .chip", has_text="Categories").click()
    expect(page.locator(".del-row", has_text="Snacks")).to_be_visible()
    page.get_by_role("button", name="Restore").click()
    page.wait_for_url(f"**/categories/{snack['aid']}")
    expect(page.get_by_text("Category restored")).to_be_visible()
    page.goto("/categories/deleted")
    expect(page.get_by_text("Nothing deleted")).to_be_visible()
