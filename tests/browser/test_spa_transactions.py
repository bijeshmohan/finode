"""The React app's Transactions page in a browser: the details sheet, Delete, the Filter sheet, upcoming and Show more
(ports of tests/browser/test_transactions_page.py and test_side_panel.py)."""

import re
from datetime import date, timedelta

import pytest
from playwright.sync_api import Browser, Page, expect

from ..books import leg
from .conftest import Api

TODAY = date.today()


def add(api: Api, books, payee, target, source, amount="100", **extra):
    return api.post(
        "/transactions/",
        payee=payee,
        postings=[leg(books[target], "debit", amount), leg(books[source], "credit", amount)],
        **extra,
    )


def row(page: Page, text: str):
    return page.get_by_role("button", name=re.compile(re.escape(text)))


def open_row(page: Page, text: str):
    """Tap a row on its title: its middle can be the related pill, which opens the other entry (as on the web page)."""
    row(page, text).get_by_text(text, exact=True).click()


def sheet(page: Page):
    return page.get_by_role("dialog", name="Transaction details")


def test_tapping_a_row_opens_the_details_sheet(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    add(spa_api, spa_books, "Swiggy", "food", "card", "597")
    page.goto("/transactions")
    row(page, "Swiggy").click()
    expect(sheet(page)).to_be_visible()
    expect(sheet(page)).to_contain_text("597.00")
    expect(sheet(page)).not_to_contain_text("−597.00")
    expect(sheet(page)).to_contain_text("Paid from")


def test_the_sheet_closes_with_escape_and_with_a_tap_outside(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    add(spa_api, spa_books, "Swiggy", "food", "card")
    page.goto("/transactions")
    row(page, "Swiggy").click()
    expect(sheet(page)).to_contain_text("Paid from")
    page.keyboard.press("Escape")
    expect(sheet(page)).to_be_hidden()
    row(page, "Swiggy").click()
    expect(sheet(page)).to_contain_text("Paid from")
    page.wait_for_function("() => document.getAnimations().length === 0")
    page.mouse.click(20, 60)  # on the dimmed page behind it
    expect(sheet(page)).to_be_hidden()


def test_deleting_an_entry_asks_first_and_it_is_gone_for_good(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    add(spa_api, spa_books, "Swiggy", "food", "card")
    page.goto("/transactions")
    row(page, "Swiggy").click()
    asked = []
    page.once("dialog", lambda d: (asked.append(d.message), d.dismiss()))
    sheet(page).get_by_role("button", name="Delete").click()
    assert "cannot be undone" in asked[0]
    assert any(t["payee"] == "Swiggy" for t in spa_api.get("/transactions/")), "dismissing deletes nothing"
    page.once("dialog", lambda d: d.accept())
    sheet(page).get_by_role("button", name="Delete").click()
    expect(row(page, "Swiggy")).to_have_count(0)
    expect(page.get_by_role("status").filter(has_text="Transaction deleted")).to_be_visible()
    assert not any(t["payee"] == "Swiggy" for t in spa_api.get("/transactions/"))


def pick(page: Page, label: str, choice: str):
    filters = page.get_by_role("dialog", name="Filter")
    filters.get_by_role("button", name=re.compile(f"^{label}")).click()
    page.get_by_role("dialog", name=label).get_by_role("button", name=re.compile(re.escape(choice))).first.click()


def test_the_filter_sheet_narrows_the_list_and_each_filter_can_be_removed(
    signed_in_spa_page: Page, spa_books, spa_api: Api
):
    page = signed_in_spa_page
    add(spa_api, spa_books, "Swiggy", "food", "card")
    add(spa_api, spa_books, "Landlord", "rent", "checking", "900")
    page.goto("/transactions")
    expect(page.get_by_test_id("summary")).to_contain_text("transactions")
    page.get_by_role("button", name="Filter", exact=True).click()
    pick(page, "Category", "Groceries")
    page.get_by_role("button", name="Show transactions").click()
    page.wait_for_url(re.compile(r"category="))
    expect(row(page, "Swiggy")).to_have_count(1)
    expect(row(page, "Landlord")).to_have_count(0)
    expect(page.get_by_test_id("summary")).to_contain_text("1 transaction")
    expect(page.get_by_role("button", name="Filter · 1")).to_be_visible()
    page.get_by_role("link", name="Remove the category filter").click()
    expect(row(page, "Landlord")).to_have_count(1)


def test_the_filter_lists_search_as_you_type(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    add(spa_api, spa_books, "Swiggy", "food", "card")
    add(spa_api, spa_books, "Landlord", "rent", "checking", "900")
    page.goto("/transactions")
    page.get_by_role("button", name="Filter", exact=True).click()
    page.get_by_role("button", name=re.compile("^Merchant")).click()
    page.get_by_label("Search merchant").fill("lan")
    expect(page.get_by_role("dialog").get_by_role("button", name="Swiggy")).to_have_count(0)
    page.get_by_role("dialog").get_by_role("button", name="Landlord").click()
    page.get_by_role("button", name="Show transactions").click()
    page.wait_for_url(re.compile(r"merchant=Landlord"))
    expect(row(page, "Landlord")).to_have_count(1)
    assert "account=" not in page.url, "a field left on Any is not sent"


def test_filtering_leaves_the_upcoming_row_closed_when_something_matches(
    signed_in_spa_page: Page, spa_books, spa_api: Api
):
    page = signed_in_spa_page
    add(spa_api, spa_books, "Lunch", "food", "checking", "120")
    ahead = TODAY + timedelta(days=1)
    if ahead.month != TODAY.month:
        pytest.skip("tomorrow is next month: nothing can be upcoming in this one")
    add(spa_api, spa_books, "Soon", "food", "checking", "90", date=str(ahead))
    page.goto("/transactions")
    upcoming = page.locator("details", has_text="1 upcoming")
    expect(upcoming).not_to_have_attribute("open", "")
    page.get_by_role("button", name="Filter", exact=True).click()
    pick(page, "Category", "Groceries")
    page.get_by_role("button", name="Show transactions").click()
    page.wait_for_url(re.compile(r"category="))
    expect(upcoming).not_to_have_attribute("open", "")
    expect(row(page, "Lunch")).to_be_visible()


def shops(api: Api, books, n: int, month: str = "2026-01"):
    for i in range(n):
        api.post(
            "/transactions/",
            payee=f"Shop {i:02d}",
            date=f"{month}-{i % 28 + 1:02d}",
            postings=[leg(books["food"], "debit", "10"), leg(books["checking"], "credit", "10")],
        )


def test_show_more_loads_the_rest_of_the_month_in_place(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    shops(spa_api, spa_books, 30)
    page.goto("/transactions?month=2026-01")
    expect(page.get_by_role("button", name=re.compile(r"^Shop "))).to_have_count(25)
    more = page.get_by_role("button", name=re.compile("^Show"))
    expect(more).to_contain_text("Show 5 more")
    expect(more).to_contain_text("5 left")
    more.click()
    expect(page.get_by_role("button", name=re.compile(r"^Shop "))).to_have_count(30)
    expect(page.get_by_text("That is all of January · 30 transactions")).to_be_visible()
    assert page.url.endswith("month=2026-01"), "the address did not change"


def test_deleting_after_show_more_leaves_no_duplicates(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    shops(spa_api, spa_books, 30)
    page.goto("/transactions?month=2026-01")
    page.get_by_role("button", name=re.compile("^Show")).click()
    expect(page.get_by_role("button", name=re.compile(r"^Shop "))).to_have_count(30)
    row(page, "Shop 29").click()
    page.once("dialog", lambda d: d.accept())
    sheet(page).get_by_role("button", name="Delete").click()
    expect(page.get_by_role("button", name=re.compile(r"^Shop "))).to_have_count(29)
    names = page.get_by_role("button", name=re.compile(r"^Shop ")).all_inner_texts()
    titles = [n.split("\n")[0] for n in names]
    assert len(titles) == len(set(titles)), "no entry twice"


def test_the_sheets_extras_sit_behind_a_more_row_that_keeps_edit_clear(
    signed_in_spa_page: Page, spa_books, spa_api: Api
):
    page = signed_in_spa_page
    first = add(spa_api, spa_books, "Swiggy", "food", "checking", "450")
    spa_api.post(
        "/transactions/",
        payee="Swiggy refund",
        related_id=first["id"],
        source="gmail",
        external_id="msg-1042",
        postings=[leg(spa_books["checking"], "debit", "120"), leg(spa_books["food"], "credit", "120")],
    )
    page.goto("/transactions")
    open_row(page, "Swiggy refund")
    more = sheet(page).locator("summary", has_text="More")
    expect(more).to_be_visible()
    edit = sheet(page).get_by_role("link", name="Edit")
    more_box, edit_box = more.bounding_box(), edit.bounding_box()
    assert more_box and edit_box
    assert edit_box["y"] - (more_box["y"] + more_box["height"]) >= 20, "a tap meant for More cannot reach Edit"
    before = edit_box["y"]
    more.click()
    expect(sheet(page).get_by_text("msg-1042")).to_be_visible()
    after = edit.bounding_box()
    assert after and abs(after["y"] - before) < 1, "the sheet grows upwards: Edit stays where it was"


def test_the_pill_opens_the_original_and_the_row_opens_its_own_sheet(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    first = add(spa_api, spa_books, "Amazon", "food", "card", "4998")
    spa_api.post(
        "/transactions/",
        payee="Amazon refund",
        related_id=first["id"],
        postings=[leg(spa_books["card"], "debit", "1000"), leg(spa_books["food"], "credit", "1000")],
    )
    page.goto("/transactions")
    pill = page.get_by_role("link", name=re.compile("^Related to an entry of"))
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text("4,998.00")
    pill.click()
    expect(sheet(page).get_by_role("heading", name="Amazon", exact=True)).to_be_visible()
    page.keyboard.press("Escape")
    expect(sheet(page)).to_be_hidden()
    open_row(page, "Amazon refund")
    expect(sheet(page).get_by_role("heading", name="Amazon refund")).to_be_visible()


@pytest.fixture
def wide_spa(browser: Browser, spa_server: str, signed_in_spa_page: Page):
    context = browser.new_context(viewport={"width": 1400, "height": 900}, base_url=spa_server, reduced_motion="reduce")
    context.add_cookies(signed_in_spa_page.context.cookies())
    page = context.new_page()
    page.set_default_timeout(8000)
    yield page
    context.close()


def test_the_details_open_beside_the_list_and_another_row_replaces_them(wide_spa: Page, spa_books, spa_api: Api):
    add(spa_api, spa_books, "Big Bazaar", "food", "checking", "120")
    add(spa_api, spa_books, "Landlord", "rent", "checking", "900")
    wide_spa.goto("/transactions")
    row(wide_spa, "Big Bazaar").click()
    panel = sheet(wide_spa)
    expect(panel.get_by_role("heading", name="Big Bazaar")).to_be_visible()
    row(wide_spa, "Landlord").click()  # the list is still usable beside the panel
    expect(panel.get_by_role("heading", name="Landlord")).to_be_visible()


def test_the_panel_closes_with_its_cross_and_with_escape(wide_spa: Page, spa_books, spa_api: Api):
    add(spa_api, spa_books, "Big Bazaar", "food", "checking", "120")
    wide_spa.goto("/transactions")
    row(wide_spa, "Big Bazaar").click()
    sheet(wide_spa).get_by_role("button", name="Close").click()
    expect(sheet(wide_spa)).to_be_hidden()
    row(wide_spa, "Big Bazaar").click()
    expect(sheet(wide_spa)).to_be_visible()
    wide_spa.keyboard.press("Escape")
    expect(sheet(wide_spa)).to_be_hidden()


def test_a_phone_keeps_the_bottom_sheet(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    add(spa_api, spa_books, "Big Bazaar", "food", "checking", "120")
    page.goto("/transactions")
    row(page, "Big Bazaar").click()
    expect(sheet(page).get_by_role("button", name="Close")).to_have_count(0)
    box = sheet(page).bounding_box()
    assert box and box["y"] + box["height"] >= 844 - 2, "a phone's sheet sits on the bottom edge"


def test_a_day_across_the_page_end_is_shown_whole_and_once(signed_in_spa_page: Page, spa_books, spa_api: Api):
    """January: the 31st down to the 9th one entry each, the 8th six entries (across a page of 25), then the 7th to the
    1st. The first page finishes the 8th; Show more brings the rest; nothing twice, nothing lost."""
    page = signed_in_spa_page
    days = (
        [f"2026-01-{d:02d}" for d in range(31, 8, -1)]
        + ["2026-01-08"] * 6
        + [f"2026-01-{d:02d}" for d in range(7, 0, -1)]
    )
    for i, day in enumerate(days):
        spa_api.post(
            "/transactions/",
            payee=f"Shop {i:02d}",
            date=day,
            postings=[leg(spa_books["food"], "debit", "10"), leg(spa_books["checking"], "credit", "10")],
        )
    page.goto("/transactions?month=2026-01")
    shops = page.get_by_role("button", name=re.compile(r"^Shop "))
    expect(shops).to_have_count(29)
    page.get_by_role("button", name=re.compile("^Show")).click()
    expect(shops).to_have_count(36)
    titles = [t.split("\n")[0] for t in shops.all_inner_texts()]
    assert len(set(titles)) == 36


def test_back_after_closing_a_sheet_goes_where_it_went_before(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    add(spa_api, spa_books, "Swiggy", "food", "card")
    page.goto("/")
    page.goto("/transactions")
    row(page, "Swiggy").click()
    expect(sheet(page)).to_be_visible()
    page.keyboard.press("Escape")
    expect(sheet(page)).to_be_hidden()
    page.go_back()
    expect(page).to_have_url(re.compile(r"/$"))
