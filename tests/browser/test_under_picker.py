"""The Under field of the category form is our own sheet, not the browser's list; the account form chooses a kind."""

from playwright.sync_api import Page, expect

from .conftest import Api


def test_a_new_account_without_a_kind_is_told_to_choose_one(page: Page, books):
    page.goto("/accounts/new")
    page.locator('input[name="name"]').fill("Nowhere")
    page.get_by_role("button", name="Add account").click()
    expect(page.locator("#form-error")).to_contain_text("kind")


def test_under_on_the_category_form_can_be_none(page: Page, books, api: Api):
    group = api.post("/categories/", name="Food", kind="spending")
    page.goto(f"/categories/new?parent={group['id']}")
    button = page.locator(".field-pick")
    expect(button).to_have_text("Food")
    button.click()
    page.locator("#row-picker [data-pick-option='']").click()
    expect(button).to_have_text("None (top level)")
    assert page.locator('select[name="parent_id"]').input_value() == ""
