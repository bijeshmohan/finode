"""Coming up: a line in the sum behind Ready to assign opens one list of what is dated ahead and what rules will record;
an account's page says what its balance will be after the entries dated ahead."""

import calendar
from datetime import timedelta

import pytest
from playwright.sync_api import Page, expect

from app.clock import local_today

from ..books import leg
from .conftest import Api


@pytest.fixture
def ahead(books, api: Api):
    """Two payments later this month: an entry and, from the rule's own start, an occurrence. Skipped on the month's last day."""
    today = local_today()
    last = calendar.monthrange(today.year, today.month)[1]
    if today.day >= last - 1:
        pytest.skip("needs two days left in the month")
    api.post(
        "/transactions/",
        payee="Cab",
        date=str(today + timedelta(days=1)),
        postings=[leg(books["food"], "debit", "70"), leg(books["checking"], "credit", "70")],
    )
    api.post(
        "/recurring/",
        payee="Landlord",
        from_account_id=books["checking"]["id"],
        to_account_id=books["roots"]["Expenses"],
        category_id=books["rent"]["id"],
        amount="1500",
        frequency="monthly",
        start_date=str(today + timedelta(days=2)),
    )


def test_the_sum_says_what_is_coming_up_and_the_list_opens_from_it(page: Page, books, ahead):
    page.goto("/budget")
    page.locator(".budget-head .calc-info summary").click()
    note = page.locator(".calc-coming .coming-note")
    expect(note).to_contain_text("2 payments coming up by")
    expect(note).to_contain_text("1,570.00")
    expect(page.locator(".calc-panel .calc-note")).to_contain_text("counted up to today")
    note.click()
    page.wait_for_url("**/budget/coming-up")
    expect(page.locator("h1")).to_have_text("Coming up")
    expect(page.locator("a.tx", has_text="Cab")).to_be_visible()
    landlord = page.locator("a.tx", has_text="Landlord")
    expect(landlord).to_contain_text("Repeats")
    landlord.click()
    page.wait_for_url("**/recurring/**/edit")


def test_nothing_is_said_when_nothing_is_coming_up(page: Page, books):
    page.goto("/budget")
    page.locator(".budget-head .calc-info summary").click()
    expect(page.locator(".calc-panel")).to_be_visible()
    expect(page.locator(".calc-coming .coming-note")).to_have_count(0)


def test_an_account_says_what_its_balance_will_be_after_what_is_coming_up(page: Page, books, ahead):
    page.goto(f"/accounts/{books['checking']['id']}")
    expect(page.locator("[data-balance-after]")).to_have_text("₹4,930.00 after the 1 coming up")
