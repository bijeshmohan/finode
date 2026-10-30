"""The to-do bell: a count in the top bar that appears after the page loads, and a sheet where each item is fixed."""

from playwright.sync_api import Page, expect

from .conftest import Api


def loan_payment(api: Api, books: dict):
    loan = api.post("/accounts/", name="Home loan", parent_id=books["roots"]["Liabilities"], on_budget=False)
    emi = api.post("/accounts/", name="EMI", parent_id=books["roots"]["Expenses"])
    api.post(
        "/transactions/",
        payee="EMI payment",
        postings=[
            {"account": loan["aid"], "side": "debit", "amount": "500"},
            {"account": books["checking"]["aid"], "side": "credit", "amount": "500"},
        ],
    )
    return emi


def choose_until_done(select, sheet, value):
    """Pick the category; htmx may not have wired the freshly swapped-in form yet (slow runs), so pick again."""
    for attempt in range(4):
        select.select_option(value)
        try:
            expect(sheet).to_contain_text("Nothing needs you", timeout=2000)
            return
        except AssertionError:
            if attempt == 3:
                raise
            select.select_option("")


def test_the_bell_has_no_count_when_nothing_needs_you(page: Page, books):
    page.goto("/")
    expect(page.locator(".todo-open").first).to_be_visible()
    expect(page.locator("#todo-count-bar")).to_be_hidden()
    page.locator(".topbar .todo-open").click()
    expect(page.locator("#todo-sheet")).to_be_visible()
    expect(page.locator("#todo-sheet-body")).to_contain_text("Nothing needs you")


def test_a_payment_with_no_category_is_fixed_from_the_sheet_and_the_count_follows(page: Page, books, api: Api):
    emi = loan_payment(api, books)
    page.goto("/accounts")
    expect(page.locator("#todo-count-bar")).to_have_text("1")
    page.locator(".topbar .todo-open").click()
    sheet = page.locator("#todo-sheet-body")
    expect(sheet).to_contain_text("1 payment has no category")
    choose_until_done(sheet.locator("select"), sheet, emi["aid"])
    expect(page.locator("#todo-count-bar")).to_be_hidden()
    entry = next(t for t in api.get("/transactions/") if t["payee"] == "EMI payment")
    assert emi["aid"] in {p["category"] for p in entry["postings"]}


def test_the_budgets_page_has_no_needs_you_line_any_more(page: Page, books, api: Api):
    loan_payment(api, books)
    page.goto("/budget")
    expect(page.locator("#budget")).to_be_visible()
    expect(page.locator(".need-line")).to_have_count(0)
