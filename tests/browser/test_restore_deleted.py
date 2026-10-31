"""Restoring a deleted entry from the Recently deleted page."""

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def test_restore_puts_the_entry_back_and_it_leaves_the_list(page: Page, books, api: Api):
    entry = api.post(
        "/transactions/",
        payee="Lunch",
        postings=[
            leg(books["food"], "debit", "120"),
            leg(books["checking"], "credit", "120"),
        ],
    )
    page.goto("/settings")
    page.get_by_role("link", name="Recently deleted").click()
    page.locator(".chips .chip", has_text="Transactions").click()
    expect(page.get_by_text("Nothing deleted")).to_be_visible()
    api.delete(f"/transactions/{entry['id']}")
    page.reload()
    expect(page.locator(".del-row", has_text="Lunch")).to_be_visible()
    page.get_by_role("button", name="Restore").click()
    expect(page.get_by_text("Transaction restored")).to_be_visible()
    expect(page.get_by_text("Nothing deleted")).to_be_visible()
    page.goto("/transactions")
    expect(page.locator("a.tx", has_text="Lunch")).to_be_visible()


def test_restoring_a_deleted_category_opens_it_again(page: Page, books, api: Api):
    snack = api.post("/accounts/", name="Snacks", parent_id=books["roots"]["Expenses"])
    api.post(
        "/transactions/",
        postings=[
            leg(snack, "debit", "5"),
            leg(books["checking"], "credit", "5"),
        ],
    )
    api.post(f"/categories/{snack['id']}/delete")  # it has an entry, so it is closed
    page.goto("/settings")
    page.get_by_role("link", name="Recently deleted").click()
    page.locator(".chips .chip", has_text="Categories").click()
    expect(page.locator(".del-row", has_text="Snacks")).to_be_visible()
    page.get_by_role("button", name="Restore").click()
    page.wait_for_url(f"**/categories/{snack['id']}")
    expect(page.get_by_text("Category restored")).to_be_visible()
    page.goto("/categories/deleted")
    expect(page.get_by_text("Nothing deleted")).to_be_visible()
