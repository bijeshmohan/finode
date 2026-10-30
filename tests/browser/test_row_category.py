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


# ---- the category sheet ------------------------------------------------------------------------


def test_a_category_is_chosen_in_a_sheet(page: Page, books, api: Api):
    api.post("/accounts/", name="Dining", parent_id=books["roots"]["Expenses"])
    page.goto("/transactions/new")
    expect(page.locator('[data-side-section="debit"] [data-side-title]')).to_have_text("Category")
    expect(page.locator('[data-side-section="credit"] [data-side-title]')).to_have_text("Paid from")
    button = page.locator('[data-rows="debit"] [data-pick]:visible')
    expect(button).to_have_text("Choose category…")
    button.click()
    dialog = page.locator("#row-picker")
    expect(dialog).to_be_visible()
    expect(dialog.locator("[data-pick-option]")).to_have_count(3)
    dialog.locator("[data-pick-search]").fill("din")
    expect(dialog.locator("[data-pick-option]")).to_have_count(1)
    dialog.locator("[data-pick-option]").click()
    expect(dialog).to_be_hidden()
    expect(button).to_have_text("Dining")
    assert page.input_value('[data-rows="debit"] select') != ""
    page.fill("#total", "40")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = api.get("/transactions/")[:1]
    dining = next(a["aid"] for a in api.get("/accounts/") if a["name"] == "Dining")
    assert {p["category"] for p in entry["postings"]} == {None, dining}


def test_the_last_categories_used_come_first_and_a_new_one_can_be_made(page: Page, books, api: Api):
    page.goto("/transactions/new")
    button = page.locator('[data-rows="debit"] [data-pick]:visible')
    button.click()
    page.locator("#row-picker [data-pick-option]", has_text="Rent").click()
    expect(button).to_have_text("Rent")
    button.click()
    first = page.locator("#row-picker [data-pick-list] li").first
    expect(first).to_have_text("Used lately")
    expect(page.locator("#row-picker [data-pick-option]").first).to_have_text("Rent")
    expect(page.locator("#row-picker [data-pick-new]")).to_be_visible()


def test_income_shows_the_earning_categories_and_a_transfer_lists_accounts(page: Page, books):
    page.goto("/transactions/new")
    page.get_by_role("button", name="Income", exact=True).click()
    expect(page.locator('[data-side-section="credit"] [data-side-title]')).to_have_text("Category")
    expect(page.locator('[data-side-section="debit"] [data-side-title]')).to_have_text("Received in")
    page.locator('[data-rows="credit"] [data-pick]:visible').click()
    expect(page.locator("#row-picker [data-pick-option]")).to_have_text(["Salary"])
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.locator('[data-rows="debit"] [data-pick]:visible').click()
    options = page.locator("#row-picker [data-pick-option]")
    expect(options.first).to_be_visible()
    assert "Salary" not in options.all_inner_texts() and "Checking" in " ".join(options.all_inner_texts())
