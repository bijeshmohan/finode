"""A card's bill in a browser: the two days on the account form and Pay bill on the card's page."""

import re
from datetime import timedelta

from playwright.sync_api import Page, expect

from app.clock import local_today

from ..books import leg


def test_the_days_are_asked_only_for_a_card_or_loan(page: Page, books, api):
    cards = api.post("/accounts/", name="Cards", parent_id=books["roots"]["Liabilities"])
    api.post("/accounts/", name="Visa Gold", parent_id=cards["id"])
    banks = api.post("/accounts/", name="Banks", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="HDFC", parent_id=banks["id"])
    page.goto("/accounts/new")
    days = page.locator("[data-bill-fields]")
    expect(days).to_be_hidden()
    kind = page.locator("[data-kind-chip]")
    kind.filter(has_text="Cards").click()
    expect(days).to_be_visible()
    kind.filter(has_text="Banks").click()
    expect(days).to_be_hidden()
    assert page.locator('[data-bill-fields] input[name="statement_day"]').is_disabled(), "hidden: not sent"
    kind.filter(has_text="Cards").click()
    page.fill('input[name="name"]', "Amex")
    page.fill('input[name="statement_day"]', "10")
    page.fill('input[name="due_day"]', "28")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    expect(page.locator(".bill")).to_be_visible()  # the days are set: the bill block is there, with nothing due yet
    expect(page.locator(".bill")).to_contain_text("Nothing due")


def test_pay_bill_opens_the_form_with_the_card_and_the_amount(page: Page, api, books):
    card = api.post("/accounts/", name="Amex", parent_id=books["roots"]["Liabilities"], statement_day=1, due_day=20)
    long_ago = str(local_today() - timedelta(days=75))
    api.post(
        "/transactions/",
        payee="Flights",
        date=long_ago,
        postings=[leg(books["food"], "debit", "1250"), leg(card, "credit", "1250")],
    )
    page.goto(f"/accounts/{card['id']}")
    expect(page.locator(".bill")).to_contain_text("1,250.00")
    page.get_by_role("link", name="Pay bill").click()
    page.wait_for_url("**/transactions/new**")
    expect(page.locator("#total")).to_have_value("1,250.00")
    assert (
        page.locator('[data-rows="debit"] select[name="account"]')
        .evaluate("s => s.selectedOptions[0].textContent")
        .strip()
        == "Amex"
    )
    assert page.locator('[data-rows="credit"] select[name="account"]').input_value() == "", (
        "the account paid from is left to choose"
    )
