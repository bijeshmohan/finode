"""On a wide screen with a mouse a transaction's details open beside the list; anywhere else they are a sheet."""

from datetime import date

import pytest
from playwright.sync_api import Browser, Page, expect

from .conftest import Api

TODAY = date.today().isoformat()


@pytest.fixture
def wide(browser: Browser, live_server: str):
    context = browser.new_context(
        viewport={"width": 1400, "height": 900}, base_url=live_server, reduced_motion="reduce"
    )
    page = context.new_page()
    page.set_default_timeout(8000)
    yield page
    context.close()


def two_entries(api: Api, books):
    for payee, amount in (("Big Bazaar", "120"), ("Landlord", "900")):
        api.post(
            "/transactions/",
            date=TODAY,
            payee=payee,
            postings=[
                {"category_id": books["food"]["id"], "side": "debit", "amount": amount},
                {"account_id": books["checking"]["id"], "side": "credit", "amount": amount},
            ],
        )


def test_the_details_open_beside_the_list_and_another_row_replaces_them(wide: Page, books, api: Api):
    two_entries(api, books)
    wide.goto("/transactions")
    wide.locator("a.tx", has_text="Big Bazaar").click()
    panel = wide.locator("dialog.side-panel[open]")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Big Bazaar")
    column = wide.locator("main").bounding_box()
    box = panel.bounding_box()
    assert column["x"] + column["width"] <= box["x"], "the list is not under the panel"
    wide.locator("a.tx", has_text="Landlord").click()  # the list is still there to tap
    expect(panel).to_contain_text("Landlord")
    expect(wide.locator("a.tx.is-open")).to_have_count(1)
    expect(wide.locator("a.tx.is-open")).to_contain_text("Landlord")


def test_the_panel_closes_with_its_cross_and_with_escape(wide: Page, books, api: Api):
    two_entries(api, books)
    wide.goto("/transactions")
    wide.locator("a.tx", has_text="Big Bazaar").click()
    wide.locator(".panel-close").click()
    expect(wide.locator("dialog.side-panel[open]")).to_have_count(0)
    expect(wide.locator("a.tx.is-open")).to_have_count(0)
    wide.locator("a.tx", has_text="Big Bazaar").click()
    expect(wide.locator("dialog.side-panel[open]")).to_be_visible()
    wide.keyboard.press("Escape")
    expect(wide.locator("dialog.side-panel[open]")).to_have_count(0)


def test_a_phone_and_a_narrow_window_keep_the_bottom_sheet(page: Page, books, api: Api):
    two_entries(api, books)
    page.goto("/transactions")
    page.locator("a.tx", has_text="Big Bazaar").click()
    expect(page.locator("dialog#txn-sheet[open]")).to_be_visible()
    assert page.evaluate("document.querySelector('#txn-sheet').matches(':modal')"), "a sheet over the page"
    assert not page.evaluate("document.querySelector('#txn-sheet').classList.contains('side-panel')")
