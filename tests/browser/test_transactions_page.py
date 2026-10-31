"""The transactions list in a browser: the details sheet, search and the Filter sheet."""

import re

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def add(api: Api, books, payee, target, source, amount="100"):
    return api.post(
        "/transactions/",
        payee=payee,
        postings=[
            leg(books[target], "debit", amount),
            leg(books[source], "credit", amount),
        ],
    )


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
    page.wait_for_function("() => document.getAnimations().length === 0")  # the sheet has finished sliding up
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
    page.get_by_role("link", name="Repeat").click()
    page.wait_for_url("**/transactions/new?repeat=*")
    assert page.input_value("#total") == "1,286.00" and page.input_value("#payee") == "DMart"
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
    assert [t["payee"] for t in api.get("/transactions/") if t["payee"] and t["payee"] != "Opening balance"] == [
        "DMart"
    ]


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


def test_a_sheet_closed_while_loading_stays_closed(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    page.goto("/transactions")
    held = []
    page.route("**/transactions/*/sheet", lambda route: held.append(route))
    page.locator("a.tx", has_text="Swiggy").click()
    expect(page.locator("#txn-sheet .skeleton")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#txn-sheet")).to_be_hidden()
    held[0].continue_()
    page.wait_for_timeout(500)
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


def pick(page: Page, field: str, choice: str):
    page.locator(f'[data-pick="{field}"]').click()
    page.locator(f'[data-filter-list="{field}"] button', has_text=choice).first.click()


def test_the_filter_sheet_narrows_the_list_and_each_filter_can_be_removed(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    add(api, books, "Landlord", "rent", "checking", "900")
    page.goto("/transactions")
    expect(page.locator(".tx-summary")).to_contain_text("transactions")
    page.get_by_role("button", name="Filter").click()
    expect(page.locator("#tx-filter")).to_be_visible()
    pick(page, "category", "Groceries")
    expect(page.locator('[data-filter-label="category"]')).to_have_text("Groceries")
    page.get_by_role("button", name="Show transactions").click()
    page.wait_for_url(re.compile(r"category="))
    expect(page.locator("a.tx", has_text="Swiggy")).to_have_count(1)
    expect(page.locator("a.tx", has_text="Landlord")).to_have_count(0)
    expect(page.locator(".tx-summary")).to_contain_text("1 transaction")
    expect(page.locator(".tx-filter-open")).to_have_text("Filter · 1")
    page.locator(".tx-applied a").click()  # the ✕ removes it
    expect(page.locator("a.tx", has_text="Landlord")).to_have_count(1)
    expect(page.locator(".tx-applied")).to_have_count(0)


def test_the_filter_lists_search_as_you_type(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    add(api, books, "Landlord", "rent", "checking", "900")
    page.goto("/transactions")
    page.get_by_role("button", name="Filter").click()
    page.locator('[data-pick="merchant"]').click()
    page.locator('[data-filter-list="merchant"] [data-filter-search]').fill("lan")
    expect(page.locator('[data-filter-list="merchant"] li:not([hidden])')).to_have_count(1)
    page.locator('[data-filter-list="merchant"] li:not([hidden]) button').click()
    page.get_by_role("button", name="Show transactions").click()
    page.wait_for_url(re.compile(r"merchant=Landlord"))
    expect(page.locator("a.tx")).to_have_count(1)
    assert "account=" not in page.url, "a field left on Any is not sent"


def test_filtering_leaves_the_upcoming_row_closed_when_something_matches(page: Page, books, api: Api):
    from datetime import date, timedelta

    api.post(
        "/transactions/",
        payee="Lunch",
        postings=[
            leg(books["food"], "debit", "120"),
            leg(books["checking"], "credit", "120"),
        ],
    )
    api.post(
        "/transactions/",
        payee="Next month",
        date=str(date.today() + timedelta(days=40)),
        postings=[
            leg(books["food"], "debit", "90"),
            leg(books["checking"], "credit", "90"),
        ],
    )
    page.goto("/transactions")
    expect(page.locator("details.upcoming")).not_to_have_attribute("open", "")
    page.get_by_role("button", name="Filter").click()
    pick(page, "category", "Groceries")
    page.get_by_role("button", name="Show transactions").click()
    page.wait_for_url(re.compile(r"category="))
    expect(page.locator("details.upcoming")).not_to_have_attribute("open", "")
    expect(page.locator("a.tx", has_text="Lunch")).to_be_visible()


def test_the_filter_sheet_opens_with_nothing_in_it_focused(page: Page, books):
    page.goto("/transactions")
    page.get_by_role("button", name="Filter").click()
    expect(page.locator("#tx-filter")).to_be_visible()
    assert page.evaluate("document.activeElement.closest('.filter-row') === null"), (
        "no row takes the focus ring when the sheet opens"
    )


def test_show_more_loads_the_rest_of_the_month_in_place(page: Page, books, api: Api):
    for i in range(30):
        api.post(
            "/transactions/",
            payee=f"Shop {i:02d}",
            date=f"2026-01-{i % 28 + 1:02d}",
            postings=[
                leg(books["food"], "debit", "10"),
                leg(books["checking"], "credit", "10"),
            ],
        )
    page.goto("/transactions?month=2026-01")
    expect(page.locator("a.tx")).to_have_count(25)
    more = page.get_by_role("button", name=re.compile("Show"))
    expect(more).to_contain_text("Show 5 more")
    expect(more).to_contain_text("5 left")
    more.click()
    expect(page.locator("a.tx")).to_have_count(30)
    expect(page.locator(".tx-end")).to_have_text("That is all of January · 30 transactions")
    expect(page.get_by_role("button", name=re.compile("Show"))).to_have_count(0)
    assert page.url.endswith("month=2026-01"), "the address did not change"


def test_home_starts_short_and_show_more_finishes_the_month(page: Page, books, api: Api):
    for i in range(14):
        api.post(
            "/transactions/",
            payee=f"Shop {i:02d}",
            date=f"2026-01-{i + 1:02d}",
            postings=[
                leg(books["food"], "debit", "10"),
                leg(books["checking"], "credit", "10"),
            ],
        )
    page.goto("/?month=2026-01")
    expect(page.locator("a.tx")).to_have_count(8)
    page.get_by_role("button", name=re.compile("Show 6 more")).click()
    expect(page.locator("a.tx")).to_have_count(14)
    expect(page.locator(".tx-end")).to_contain_text("That is all of January")
    page.locator("a.tx").first.click()  # rows that arrived later open the details sheet too
    expect(page.locator("#txn-sheet")).to_be_visible()


def test_the_sheet_opens_on_an_account_page_and_a_category_page_and_edit_comes_back(page: Page, books, api: Api):
    add(api, books, "Swiggy", "food", "card")
    for url in (f"/accounts/{books['card']['aid']}", f"/categories/{books['food']['aid']}"):
        page.goto(url)
        page.locator("a.tx", has_text="Swiggy").click()
        expect(page.locator("#txn-sheet")).to_be_visible()
        expect(page.locator("#txn-sheet-body h2")).to_have_text("Swiggy")
        assert page.url.endswith(url), "the page itself did not change"
        page.locator("#txn-sheet a.button", has_text="Edit").click()
        page.wait_for_url(re.compile(r"/transactions/[^/]+/edit"))
        page.get_by_role("button", name="Save changes").click()
        page.wait_for_url(re.compile(re.escape(url) + r"$"))
        expect(page.locator("a.tx", has_text="Swiggy")).to_be_visible()  # the account page is fully back


def test_the_sheets_extras_sit_behind_a_more_row_that_keeps_edit_clear(page: Page, books, api: Api):
    first = api.post(
        "/transactions/",
        payee="Swiggy",
        postings=[
            leg(books["food"], "debit", "450"),
            leg(books["checking"], "credit", "450"),
        ],
    )
    api.post(
        "/transactions/",
        payee="Swiggy refund",
        related_id=first["tid"],
        source="gmail",
        external_id="msg-1042",
        postings=[
            leg(books["checking"], "debit", "120"),
            leg(books["food"], "credit", "120"),
        ],
    )
    page.goto("/transactions")
    page.locator("a.tx", has_text="Swiggy refund").click()
    sheet = page.locator("#txn-sheet")
    more = sheet.locator(".sheet-extra > summary")
    expect(more).to_have_text("More")
    assert (
        more.locator("span").bounding_box()["x"] < sheet.bounding_box()["x"] + 40
    )  # left aligned, like the rows above
    expect(sheet.locator(".sheet-related-row")).to_be_hidden()  # folded
    edit = sheet.get_by_role("link", name="Edit")
    gap = edit.bounding_box()["y"] - (more.bounding_box()["y"] + more.bounding_box()["height"])
    assert gap >= 20, gap  # a tap meant for More cannot reach Edit
    before = edit.bounding_box()["y"]
    more.click()
    expect(sheet.locator(".sheet-related-row")).to_be_visible()
    expect(sheet.get_by_text("msg-1042")).to_be_visible()
    assert abs(edit.bounding_box()["y"] - before) < 1  # the sheet grows upwards: Edit stays where it was
    assert "/edit" not in page.url
    more.click()
    expect(sheet.locator(".sheet-related-row")).to_be_hidden()
