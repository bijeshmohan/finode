"""A category on the Add screen is a chip after the accounts, with its amount beside it: typing less than the total
splits it naturally. Its sheet is a grid of tiles."""

from playwright.sync_api import Page, expect

from .conftest import Api


def top(page: Page, selector: str) -> float:
    return page.locator(selector).first.bounding_box()["y"]


def test_the_category_is_a_chip_after_the_accounts_for_expense_and_income(page: Page, books):
    page.goto("/transactions/new")
    chip = page.locator('[data-rows="debit"] [data-pick]:visible')
    expect(chip).to_have_text("Category…")
    assert top(page, '[data-side-section="credit"]') < top(page, '[data-side-section="debit"]')
    page.get_by_role("button", name="Income", exact=True).click()
    # Income: the data has the category on the From side, the screen lists it after "Received in".
    assert top(page, '[data-side-section="debit"]') < top(page, '[data-side-section="credit"]')
    page.get_by_role("button", name="Transfer", exact=True).click()
    assert top(page, '[data-side-section="credit"]') < top(page, '[data-side-section="debit"]')


def test_typing_less_than_the_total_splits_it_and_removing_a_row_goes_back_to_one(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Groceries")
    amount = page.locator('[data-rows="debit"] [data-row]:nth-child(1) [name="amount"]')
    expect(amount).to_be_visible()
    assert amount.input_value() == "100.00", "the chip carries the whole amount, in grey"
    page.fill("#total", "120")
    assert amount.input_value() == "120.00", "and follows the total"
    amount.fill("80")
    expect(page.locator('[data-rows="debit"] [data-row]')).to_have_count(2)
    assert page.input_value('[data-rows="debit"] [data-row]:nth-child(2) [name="amount"]') == "40.00"
    page.select_option('[data-rows="debit"] [data-row]:nth-child(2) select', label="Rent")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = api.get("/transactions/")[:1]
    assert sorted(p["amount"] for p in entry["postings"] if p["side"] == "debit") == ["40.00", "80.00"]


def test_removing_a_row_brings_one_category_back(page: Page, books):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    page.fill('[data-rows="debit"] [data-row]:nth-child(1) [name="amount"]', "30")
    page.click('[data-rows="debit"] [data-row]:nth-child(2) [data-remove-row]')
    expect(page.locator('[data-rows="debit"] [data-row]')).to_have_count(1)
    assert page.input_value('[data-rows="debit"] [name="amount"]') == "100.00"
    expect(page.locator('[data-rows="debit"] [data-remove-row]:visible')).to_have_count(0)


def test_the_category_sheet_is_a_grid_of_tiles_and_the_account_sheet_a_list(page: Page, books):
    page.goto("/transactions/new")
    page.locator('[data-rows="debit"] [data-pick]:visible').click()
    tiles = page.locator("#row-picker [data-pick-option]")
    expect(tiles).to_have_count(2)
    first, second = tiles.nth(0).bounding_box(), tiles.nth(1).bounding_box()
    assert abs(first["y"] - second["y"]) < 2 and first["x"] != second["x"], "two tiles side by side"
    tiles.first.click()
    page.locator('[data-rows="debit"] [data-pick]:visible').click()
    expect(page.locator('#row-picker [aria-pressed="true"]').first).to_be_visible()
    page.keyboard.press("Escape")
    page.locator('[data-rows="credit"] [data-pick]:visible').click()
    first, second = tiles.nth(0).bounding_box(), tiles.nth(1).bounding_box()
    assert first["x"] == second["x"] and first["y"] != second["y"], "accounts stay one under another"


def test_a_payments_category_is_a_chip_with_a_no_category_choice(page: Page, books, api: Api):
    loan = api.post("/accounts/", name="Home loan", parent_id=books["roots"]["Liabilities"], on_budget=False)
    api.post("/accounts/", name="EMI", parent_id=books["roots"]["Expenses"])
    page.goto("/transactions/new")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', value=loan["id"])
    chip = page.locator('[data-rows="debit"] [data-category-select] + [data-pick]')
    expect(chip).to_be_visible()
    expect(chip).to_have_text("No category")
    chip.click()
    page.locator("#row-picker [data-pick-option]", has_text="EMI").click()
    expect(chip).to_have_text("EMI")
    chip.click()
    page.locator("#row-picker [data-pick-option]", has_text="No category").click()
    expect(chip).to_have_text("No category")
    assert page.input_value('[data-rows="debit"] [data-category-select]') == ""
