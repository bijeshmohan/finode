"""The Category line of a payment into a loan or fund, in a browser: it shows only when money leaves the budget into an
account outside it, starts at the account's usual category and is saved on the line."""

from playwright.sync_api import Page, expect

from .conftest import Api


def loan_books(api: Api, books: dict) -> dict:
    loan = api.post("/accounts/", name="Home loan", parent_id=books["roots"]["Liabilities"], on_budget=False)
    emi = api.post("/accounts/", name="EMI", parent_id=books["roots"]["Expenses"])
    sip = api.post("/accounts/", name="SIP", parent_id=books["roots"]["Expenses"])
    return {"loan": loan, "emi": emi, "sip": sip}


def test_the_category_line_shows_only_when_money_leaves_the_budget(page: Page, books, api: Api):
    more = loan_books(api, books)
    page.goto("/transactions/new")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.fill("#total", "19277")
    category = page.locator('[data-rows="debit"] [data-category-select]')
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Cash")
    expect(category).to_be_hidden()  # both in the budget: nothing to say
    page.select_option('[data-rows="debit"] select', label="Home loan")
    expect(category).to_be_visible()
    assert page.input_value('[data-rows="debit"] [data-category-select]') == ""
    page.select_option('[data-rows="debit"] [data-category-select]', label="EMI")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = [t for t in api.get("/transactions/") if any(p["account"] == more["loan"]["aid"] for p in t["postings"])]
    labels = {p["account"]: p["category"] for p in entry["postings"]}
    assert labels[more["loan"]["aid"]] == more["emi"]["aid"] and labels[books["checking"]["aid"]] is None


def test_the_usual_category_of_a_loan_fills_the_line_in(page: Page, books, api: Api):
    more = loan_books(api, books)
    api.request.patch(f"/api/accounts/{more['loan']['aid']}", data={"payment_category_id": more["emi"]["aid"]})
    page.goto("/transactions/new")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Home loan")
    assert page.input_value('[data-rows="debit"] [data-category-select]') == more["emi"]["aid"]
    page.select_option('[data-rows="debit"] [data-category-select]', value="")  # the person says none
    page.select_option('[data-rows="credit"] select', label="Cash")
    page.select_option('[data-rows="credit"] select', label="Checking")
    assert page.input_value('[data-rows="debit"] [data-category-select]') == "", "a choice is not filled in again"


def test_an_edit_keeps_the_category_it_had(page: Page, books, api: Api):
    more = loan_books(api, books)
    made = api.post(
        "/transactions/",
        postings=[
            {"account": more["loan"]["aid"], "side": "debit", "amount": "500", "category": more["sip"]["aid"]},
            {"account": books["checking"]["aid"], "side": "credit", "amount": "500"},
        ],
    )
    page.goto(f"/transactions/{made['tid']}/edit")
    assert page.input_value('[data-rows="debit"] [data-category-select]') == more["sip"]["aid"]
    page.fill('input[name="payee"]', "SIP top-up")
    page.get_by_role("button", name="Save changes", exact=True).click()
    page.wait_for_url("**/transactions")
    entry = api.get(f"/transactions/{made['tid']}")
    assert {p["category"] for p in entry["postings"]} == {more["sip"]["aid"], None}
