"""Choosing an account in a sheet on the Add screen: grouped by name, with balances, searchable, the other side's account
greyed, and a new account made from it."""

from playwright.sync_api import Page, expect

from .conftest import Api


def test_an_account_is_chosen_in_a_sheet(page: Page, books, api: Api):
    page.goto("/transactions/new")
    button = page.locator('[data-rows="credit"] [data-pick]')
    expect(button).to_have_text("Choose account…")
    button.click()
    dialog = page.locator("#row-picker")
    expect(dialog).to_be_visible()
    expect(dialog.locator(".filter-title")).to_have_text("Account")
    checking = dialog.locator("[data-pick-option]", has_text="Checking")
    expect(checking.locator(".pick-balance")).to_have_text("5,000.00")
    expect(dialog.locator("[data-pick-option]", has_text="Visa").locator(".pick-balance")).to_have_text("owed 0.00")
    dialog.locator("[data-pick-search]").fill("chec")
    expect(dialog.locator("[data-pick-option]")).to_have_count(1)
    checking.click()
    expect(dialog).to_be_hidden()
    expect(button).to_have_text("Checking")
    assert page.input_value('[data-rows="credit"] select') == books["checking"]["aid"]
    page.fill("#total", "40")
    page.locator('[data-rows="debit"] [data-pick]').click()
    page.locator("#row-picker [data-pick-option]", has_text="Groceries").click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = api.get("/transactions/")[:1]
    assert {p["account"] for p in entry["postings"]} == {books["checking"]["aid"], books["food"]["aid"]}


def test_the_account_on_the_other_side_is_greyed_and_the_last_used_come_first(page: Page, books):
    page.goto("/transactions/new")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.locator('[data-rows="credit"] [data-pick]').click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").click()
    page.locator('[data-rows="debit"] [data-pick]').click()
    for same in page.locator("#row-picker [data-pick-option]", has_text="Checking").all():  # also under Used lately
        expect(same).to_be_disabled()
    expect(page.locator("#row-picker [data-pick-option]", has_text="Cash").first).to_be_enabled()
    page.keyboard.press("Escape")
    page.locator('[data-rows="credit"] [data-pick]').click()
    expect(page.locator("#row-picker [data-pick-list] li").first).to_have_text("Used lately")


def test_a_new_account_can_be_made_from_the_sheet(page: Page, books, api: Api):
    page.goto("/transactions/new")
    button = page.locator('[data-rows="credit"] [data-pick]')
    button.click()
    page.locator("#row-picker [data-pick-new]").click()
    dialog = page.locator("#quick-account")
    expect(dialog).to_be_visible()
    dialog.locator('input[name="name"]').fill("Kotak")
    dialog.get_by_role("button", name="Add account").click()
    expect(dialog).not_to_be_visible()
    expect(button).to_have_text("Kotak")
    assert any(a["name"] == "Kotak" for a in api.get("/accounts/"))


def test_the_chosen_account_is_bold_and_the_scroll_bar_stays_clear_of_the_balances(page: Page, books, api: Api):
    for number in range(25):
        api.post("/accounts/", name=f"Wallet {number:02d}", parent_id=books["roots"]["Assets"], balance="1500")
    page.goto("/transactions/new")
    page.locator('[data-rows="credit"] [data-pick]').click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").click()
    page.locator('[data-rows="credit"] [data-pick]').click()
    assert page.locator("#row-picker .tag-tick").count() == 0, "no circle: one choice closes the sheet"
    chosen = page.locator('#row-picker [aria-pressed="true"] > span:first-child').first
    assert chosen.evaluate("el => getComputedStyle(el).fontWeight") == "600"
    list_box = page.locator("#row-picker [data-pick-list]")
    assert list_box.evaluate("el => el.scrollHeight > el.clientHeight"), "the list is long enough to scroll"
    edge = list_box.bounding_box()["x"] + list_box.evaluate("el => el.clientWidth")  # where a scroll bar begins
    balance = page.locator("#row-picker .pick-balance").first.bounding_box()
    assert balance["x"] + balance["width"] <= edge, "the figures end before the scroll bar"
