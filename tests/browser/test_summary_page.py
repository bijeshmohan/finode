"""The month summary in a browser: the chart is drawn and nothing overflows a phone."""

import re
from datetime import date

from playwright.sync_api import Page, expect

from .conftest import Api

THIS_MONTH = date.today().replace(day=1)


def shift(month: date, by: int) -> date:
    index = month.year * 12 + month.month - 1 + by
    return date(index // 12, index % 12 + 1, 1)


def entry(api: Api, debit, credit, amount, when):
    api.post("/transactions/", date=when.isoformat(), postings=[
        {"account": debit["aid"], "side": "debit", "amount": amount},
        {"account": credit["aid"], "side": "credit", "amount": amount},
    ])


def test_the_trend_chart_and_the_lists_fit_a_phone(page: Page, books, api: Api):
    for back, pay, spent, rent in ((0, "5000", "400", "1500"), (1, "6000", "300", "1500"), (2, "4000", "250", "1200")):
        month = shift(THIS_MONTH, -back)
        entry(api, books["checking"], books["salary"], pay, month)
        entry(api, books["food"], books["checking"], spent, month)
        entry(api, books["rent"], books["checking"], rent, month)
    page.goto("/summary")
    expect(page.locator(".trend li")).to_have_count(6)
    heights = page.locator(".trend .bars i").evaluate_all("els => els.map(e => e.getBoundingClientRect().height)")
    assert max(heights) > 40, "the tallest bar is drawn"
    assert sum(1 for h in heights if h > 2) >= 6, "bars exist for the months with entries"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone"
    expect(page.get_by_text("Where the money went")).to_be_visible()
    # tapping a month in the chart opens that month
    page.locator(".trend li a").nth(4).click()
    expect(page).to_have_url(re.compile(f"month={shift(THIS_MONTH, -1):%Y-%m}"))
    expect(page.locator("h1")).not_to_contain_text("so far")
    page.screenshot(path="/tmp/claude-1002/summary.png", full_page=True)
