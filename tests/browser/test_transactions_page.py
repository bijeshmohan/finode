"""The transactions list in a browser: the details sheet, search and the kind chips."""

import re

from playwright.sync_api import Page, expect

from .conftest import Api


def add(api: Api, books, payee, target, source, amount="100"):
    return api.post("/transactions/", payee=payee, postings=[
        {"account": books[target]["aid"], "side": "debit", "amount": amount},
        {"account": books[source]["aid"], "side": "credit", "amount": amount},
    ])


def test_tapping_a_row_opens_the_details_sheet(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card", "597")
    page.goto("/transactions")
    page.locator("a.tx", has_text="Swiggy").click()
    sheet = page.locator("#txn-sheet")
    expect(sheet).to_be_visible()
    expect(sheet).to_contain_text("Swiggy")
    expect(sheet).to_contain_text("597.00")
    expect(sheet).not_to_contain_text("−597.00")
    expect(sheet).to_contain_text("Paid from")
    assert page.url.endswith("/transactions"), "the sheet is not a new page"


def test_the_sheet_closes_with_escape_and_with_a_tap_outside(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    page.goto("/transactions")
    page.locator("a.tx", has_text="Swiggy").click()
    expect(page.locator("#txn-sheet")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#txn-sheet")).to_be_hidden()
    page.locator("a.tx", has_text="Swiggy").click()
    expect(page.locator("#txn-sheet")).to_be_visible()
    page.mouse.click(20, 60)  # on the dimmed page behind it
    expect(page.locator("#txn-sheet")).to_be_hidden()


def test_the_sheet_opens_from_home_too(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    page.goto("/")
    page.locator("a.tx", has_text="Swiggy").click()
    expect(page.locator("#txn-sheet")).to_be_visible()
    assert page.url.rstrip("/") == page.url.split("/", 3)[0] + "//" + page.url.split("/")[2], "still on Home"


def test_add_again_opens_the_form_filled_in(page: Page, books, api: Api):
    add(api, books, "DMart", "food", "checking", "1286")
    page.goto("/transactions")
    page.locator("a.tx", has_text="DMart").click()
    page.get_by_role("link", name="Add again").click()
    page.wait_for_url("**/transactions/new?repeat=*")
    assert page.input_value("#total") == "1286.00" and page.input_value("#payee") == "DMart"
    assert page.input_value('[data-rows="credit"] select') == books["checking"]["aid"]
    assert page.input_value('[data-rows="debit"] select') == books["food"]["aid"]
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    assert len([t for t in api.get("/transactions/") if t["payee"] == "DMart"]) == 2


def test_edit_from_the_sheet_goes_to_the_edit_page(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    page.goto("/transactions")
    page.locator("a.tx", has_text="Swiggy").click()
    page.get_by_role("link", name="Edit", exact=True).click()
    page.wait_for_url("**/edit")
    assert page.input_value("#payee") == "Swiggy"


def test_deleting_from_the_sheet(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    add(api, books, "DMart", "food", "checking")
    page.goto("/transactions")
    page.locator("a.tx", has_text="Swiggy").click()
    page.locator("#txn-sheet").get_by_role("button", name="Delete").click()
    page.wait_for_url("**/transactions")
    expect(page.locator("a.tx", has_text="Swiggy")).to_have_count(0)
    expect(page.locator("a.tx", has_text="DMart")).to_have_count(1)
    assert [t["payee"] for t in api.get("/transactions/") if t["payee"] and t["payee"] != "Opening balance"] == ["DMart"]


def test_a_sheet_opens_at_once_with_placeholders_and_closes_if_the_content_never_comes(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    page.goto("/transactions")
    held = []
    page.route("**/transactions/*/sheet", lambda route: held.append(route))
    page.locator("a.tx", has_text="Swiggy").click()
    expect(page.locator("#txn-sheet")).to_be_visible()
    expect(page.locator("#txn-sheet .skeleton")).to_be_visible()
    held[0].abort()
    expect(page.locator("#txn-sheet")).to_be_hidden()


def test_undo_in_the_toast_brings_a_deleted_entry_back(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    page.goto("/transactions")
    page.locator("a.tx", has_text="Swiggy").click()
    page.locator("#txn-sheet").get_by_role("button", name="Delete").click()
    expect(page.locator("a.tx", has_text="Swiggy")).to_have_count(0)
    page.locator(".toast .toast-undo").click()
    expect(page.locator("a.tx", has_text="Swiggy")).to_have_count(1)
    assert any(t["payee"] == "Swiggy" for t in api.get("/transactions/"))


def test_the_kind_chips_filter(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    api.post("/transactions/", payee="Employer", postings=[
        {"account": books["checking"]["aid"], "side": "debit", "amount": "5000"},
        {"account": books["salary"]["aid"], "side": "credit", "amount": "5000"}])
    page.goto("/transactions")
    page.get_by_role("link", name="Income", exact=True).click()
    page.wait_for_url(re.compile(r"kind=income"))
    expect(page.locator("a.tx", has_text="Employer")).to_have_count(1)
    expect(page.locator("a.tx", has_text="Swiggy")).to_have_count(0)
    expect(page.get_by_role("link", name="Income", exact=True)).to_have_attribute("aria-pressed", "true")
    page.get_by_role("link", name="Income", exact=True).click()  # the chosen chip again shows everything
    expect(page.locator("a.tx", has_text="Swiggy")).to_have_count(1)


def test_choosing_a_kind_chip_leaves_the_upcoming_row_closed(page: Page, books, api: Api):
    from datetime import date, timedelta

    api.post("/transactions/", payee="Lunch", postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "120"},
        {"account": books["checking"]["aid"], "side": "credit", "amount": "120"},
    ])
    api.post("/transactions/", payee="Next month", date=str(date.today() + timedelta(days=40)), postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "90"},
        {"account": books["checking"]["aid"], "side": "credit", "amount": "90"},
    ])
    page.goto("/transactions")
    expect(page.locator("details.upcoming")).not_to_have_attribute("open", "")
    page.get_by_role("link", name="Expense", exact=True).click()
    page.wait_for_url(re.compile(r"kind=expense$"))
    expect(page.locator("details.upcoming")).to_have_count(1)
    expect(page.locator("details.upcoming")).not_to_have_attribute("open", "")
    expect(page.locator("a.tx", has_text="Lunch")).to_be_visible()
