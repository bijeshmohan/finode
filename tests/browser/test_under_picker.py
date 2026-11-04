"""The Under field of the account and category forms is our own sheet, not the browser's list."""

from playwright.sync_api import Page, expect

from .conftest import Api


def test_under_on_the_account_form_opens_a_sheet_and_the_choice_sets_the_form(page: Page, books, api: Api):
    page.goto("/accounts/new")
    button = page.locator(".field-pick")
    expect(button).to_have_text("Choose…")
    expect(page.locator('select[name="parent_id"]')).to_have_css("opacity", "0")
    button.click()
    expect(page.locator("#row-picker")).to_be_visible()
    page.locator("#row-picker [data-pick-search]").fill("liab")
    page.locator("#row-picker [data-pick-option]", has_text="Liabilities").first.click()
    expect(button).to_have_text("Liabilities")
    expect(page.locator('[data-budget-fields] input[name="on_budget"]')).not_to_be_checked()  # a card starts outside
    page.locator('input[name="name"]').fill("Axis Card")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url("**/accounts/*")
    assert any(a["name"] == "Axis Card" for a in api.get("/accounts/"))


def test_a_new_account_without_a_group_is_told_to_choose_one(page: Page, books):
    page.goto("/accounts/new")
    page.locator('input[name="name"]').fill("Nowhere")
    page.get_by_role("button", name="Add account").click()
    expect(page.locator("#form-error")).not_to_be_empty()


def test_under_on_the_category_form_can_be_none(page: Page, books, api: Api):
    group = api.post("/categories/", name="Food", kind="spending")
    page.goto(f"/categories/new?parent={group['id']}")
    button = page.locator(".field-pick")
    expect(button).to_have_text("Food")
    button.click()
    page.locator("#row-picker [data-pick-option='']").click()
    expect(button).to_have_text("None (top level)")
    assert page.locator('select[name="parent_id"]').input_value() == ""
