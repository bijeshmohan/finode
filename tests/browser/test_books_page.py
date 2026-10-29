"""Books accounts and the payments that need a category, in a browser."""

from playwright.sync_api import Page, expect

from .conftest import Api


def test_an_extra_books_account_is_made_from_the_sheet(page: Page, books, api: Api):
    api.post("/accounts/", name="EMI", parent_id=books["roots"]["Expenses"])
    page.goto("/settings")
    page.get_by_role("link", name="Books accounts").click()
    expect(page.get_by_role("heading", name="Books accounts")).to_be_visible()
    expect(page.locator(".books-row", has_text="EMI")).to_be_visible()
    page.get_by_role("button", name="New books account").click()
    sheet = page.locator("#books-sheet")
    expect(sheet.get_by_role("heading", name="New books account")).to_be_visible()
    sheet.get_by_label("Name").fill("Interest")
    sheet.get_by_label("Feeds this category").select_option(label="EMI")
    sheet.get_by_role("button", name="Add").click()
    page.wait_for_url("**/books")
    row = page.locator(".books-row", has_text="Interest")
    expect(row).to_be_visible()
    expect(row).to_contain_text("feeds EMI")
    row.click()
    expect(page.locator("#books-sheet").get_by_label("Name")).to_have_value("Interest")
    page.locator("#books-sheet").get_by_role("button", name="Close", exact=True).click()
    page.wait_for_url("**/books")
    expect(page.locator(".books-row", has_text="Interest")).to_contain_text("closed")


def test_a_payment_without_a_category_is_given_one_from_the_budget(page: Page, books, api: Api):
    loan = api.post("/accounts/", name="Home loan", parent_id=books["roots"]["Liabilities"], on_budget=False)
    emi = api.post("/accounts/", name="EMI", parent_id=books["roots"]["Expenses"])
    api.post(
        "/transactions/",
        payee="SBI",
        postings=[
            {"account": loan["aid"], "side": "debit", "amount": "1000"},
            {"account": books["checking"]["aid"], "side": "credit", "amount": "1000"},
        ],
    )
    page.goto("/budget")
    page.get_by_role("button", name="1 thing needs you").click()
    panel = page.locator("#attn-panel")
    expect(panel).to_contain_text("1 payment has no category")
    panel.get_by_label("Category for SBI").select_option(label="EMI")
    expect(page.locator("#attn-panel")).to_have_count(0)  # nothing needs a decision any more
    [entry] = [t for t in api.get("/transactions/") if t["payee"] == "SBI"]
    assert emi["aid"] in {p["category"] for p in entry["postings"]}
