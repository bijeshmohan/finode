"""The recurring transaction form shares the transaction form's rows: a split saves as one rule."""

from playwright.sync_api import Page, expect

from .conftest import Api


def test_a_split_rule_from_the_form(page: Page, books, api: Api):
    page.goto("/recurring/new")
    page.fill("#total", "1000")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.fill('[data-rows="debit"] [name="amount"]', "700")
    page.select_option('[data-rows="debit"] [data-row]:nth-child(1) select', label="Rent")
    page.select_option('[data-rows="debit"] [data-row]:nth-child(2) select', label="Groceries")
    assert page.eval_on_selector_all('[data-rows="debit"] [name="amount"]', "e => e.map(x => x.value)") == ["700", "300.00"]
    page.fill('input[name="payee"]', "Landlord")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/recurring")
    expect(page.get_by_text("Landlord")).to_be_visible()
    [rule] = api.get("/recurring/")
    assert rule["from_account"] is None and len(rule["postings"]) == 3, "more than one account on a side is a split"


def test_a_plain_rule_stays_plain(page: Page, books, api: Api):
    page.goto("/recurring/new")
    page.fill("#total", "500")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Rent")
    page.fill('input[name="start"]', "2999-01-01")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/recurring")
    [rule] = api.get("/recurring/")
    assert rule["from_account"] == books["checking"]["aid"] and rule["postings"] == []
