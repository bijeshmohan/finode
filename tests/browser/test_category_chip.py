"""A category on the Add screen is a chip after the accounts, with no amount of its own until the entry is split; its
sheet is a grid of tiles."""

from playwright.sync_api import Page, expect

from .conftest import Api


def top(page: Page, selector: str) -> float:
    return page.locator(selector).first.bounding_box()["y"]


def test_the_category_is_a_chip_after_the_accounts_for_expense_and_income(page: Page, books):
    page.goto("/transactions/new")
    chip = page.locator('[data-rows="debit"] [data-pick]:visible')
    expect(chip).to_have_text("Choose category…")
    expect(page.locator('[data-rows="debit"] [name="amount"]')).to_be_hidden()
    assert top(page, '[data-side-section="credit"]') < top(page, '[data-side-section="debit"]')
    page.get_by_role("button", name="Income", exact=True).click()
    # Income: the data has the category on the From side, the screen lists it after "Received in".
    assert top(page, '[data-side-section="debit"]') < top(page, '[data-side-section="credit"]')
    expect(page.locator('[data-rows="credit"] [name="amount"]')).to_be_hidden()
    page.get_by_role("button", name="Transfer", exact=True).click()
    assert top(page, '[data-side-section="credit"]') < top(page, '[data-side-section="debit"]')
    expect(page.locator('[data-rows="debit"] [name="amount"]')).to_be_visible()


def test_a_lone_category_follows_the_total_and_a_split_shows_the_amounts(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.fill("#total", "120")
    assert page.input_value('[data-rows="debit"] [name="amount"]') == "120.00", "the chip is the whole amount"
    link = page.locator('[data-side-section="debit"] [data-split-on]')
    expect(link).to_be_visible()
    link.click()
    expect(link).to_be_hidden()
    page.fill('[data-rows="debit"] [data-row]:nth-child(1) [name="amount"]', "80")
    expect(page.locator('[data-rows="debit"] [data-row]')).to_have_count(2)
    page.select_option('[data-rows="debit"] [data-row]:nth-child(2) select', label="Rent")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = api.get("/transactions/")[:1]
    assert sorted(p["amount"] for p in entry["postings"] if p["side"] == "debit") == ["40.00", "80.00"]


def test_removing_down_to_one_category_goes_back_to_the_chip(page: Page, books):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    page.locator('[data-side-section="debit"] [data-split-on]').click()
    page.fill('[data-rows="debit"] [data-row]:nth-child(1) [name="amount"]', "30")
    page.click('[data-rows="debit"] [data-row]:nth-child(2) [data-remove-row]')
    expect(page.locator('[data-rows="debit"] [name="amount"]')).to_be_hidden()
    assert page.input_value('[data-rows="debit"] [name="amount"]') == "100.00"
    expect(page.locator('[data-side-section="debit"] [data-split-on]')).to_be_visible()


def test_an_entry_with_two_categories_opens_as_a_split(page: Page, books, api: Api):
    entry = api.post(
        "/transactions/",
        postings=[
            {"account": books["food"]["aid"], "side": "debit", "amount": "60"},
            {"account": books["rent"]["aid"], "side": "debit", "amount": "40"},
            {"account": books["checking"]["aid"], "side": "credit", "amount": "100"},
        ],
    )
    page.goto(f"/transactions/{entry['tid']}/edit")
    expect(page.locator('[data-rows="debit"] [name="amount"]').first).to_be_visible()
    expect(page.locator('[data-side-section="debit"] [data-split-on]')).to_be_hidden()


def test_the_category_sheet_is_a_grid_of_tiles_and_the_account_sheet_a_list(page: Page, books):
    page.goto("/transactions/new")
    page.locator('[data-rows="debit"] [data-pick]:visible').click()
    tiles = page.locator("#row-picker [data-pick-option]")
    expect(tiles).to_have_count(2)
    first, second = tiles.nth(0).bounding_box(), tiles.nth(1).bounding_box()
    assert abs(first["y"] - second["y"]) < 2 and first["x"] != second["x"], "two tiles side by side"
    tiles.first.click()
    page.locator('[data-rows="debit"] [data-pick]:visible').click()
    expect(page.locator('#row-picker [aria-pressed="true"]').first).to_be_visible()  # also under Used lately
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
    page.select_option('[data-rows="debit"] select', value=loan["aid"])
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
