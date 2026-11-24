"""The React app's Accounts page and an account's page in a browser (ports of test_accounts_page.py,
test_account_info.py, test_card_bills.py and test_fixed_parents.py)."""

import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from playwright.sync_api import Page, expect

from finode.clock import local_today
from finode.models.account import Account

from ..books import leg
from .conftest import Api


def cards(page: Page) -> list[str]:
    """The names on the account cards that are shown."""
    return page.locator("main section a[href^='/accounts/']:not([href*='new'])").evaluate_all(
        "els => els.filter(e => !e.closest('h2')).map(e => e.querySelector('span > span:not(:has(svg))').textContent)"
    )


def kind(page: Page, name: str):
    return page.locator("main section").filter(has=page.get_by_role("heading", name=name, exact=True))


def nested(api: Api, books):
    """Two Prepaid Wallets and a Cash account beside the books' Bank Accounts and card."""
    api.post("/accounts/", name="HDFC", type="assets.wallet", balance="100")
    api.post("/accounts/", name="SBI", type="assets.wallet", balance="50")
    api.post("/accounts/", name="Rainy", type="assets.cash")


def test_every_kind_is_a_row_of_cards_under_its_heading(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    nested(api, books)
    page.goto("/accounts")
    expect(kind(page, "Prepaid Wallet")).to_contain_text("2 accounts")
    assert {"HDFC", "SBI", "Rainy", "Checking", "Cash"} <= set(cards(page))
    assert "Opening Balances" not in cards(page), "Equity is not listed"
    assert page.locator("main details").count() == 0, "nothing folds"
    expect(page.locator("main h2")).to_have_text(["Bank Account", "Cash", "Credit Card", "Prepaid Wallet"])


def test_a_long_row_scrolls_sideways_on_its_own_and_the_page_does_not(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    for number in range(8):
        api.post("/accounts/", name=f"Wallet {number}", type="assets.wallet")
    api.post("/accounts/", name="Fund A", type="assets.cash")
    page.goto("/accounts")
    wallets, funds = kind(page, "Prepaid Wallet"), kind(page, "Cash")
    expect(wallets).to_contain_text("8 accounts")
    rail = wallets.locator("div").filter(has=page.get_by_role("link", name="Add account")).last
    assert rail.evaluate("el => el.scrollWidth > el.clientWidth + 1"), "eight cards run past the edge"
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    rail.evaluate("el => { el.scrollLeft = el.scrollWidth }")
    assert rail.evaluate("el => el.scrollLeft") > 0
    funds_rail = funds.locator("div").filter(has=page.get_by_role("link", name="Add account")).last
    assert funds_rail.evaluate("el => el.scrollLeft") == 0


def test_with_a_mouse_a_long_row_shows_a_scrollbar_to_drag_and_on_a_touch_screen_it_does_not(
    signed_in_page: Page, api: Api, books, browser, server: str
):
    """A mouse cannot swipe and its wheel scrolls the page, so a desktop needs a scrollbar to reach the last cards."""
    page = signed_in_page
    page.set_viewport_size({"width": 1280, "height": 800})
    for number in range(8):
        api.post("/accounts/", name=f"Wallet {number}", type="assets.wallet")
    page.goto("/accounts")
    expect(kind(page, "Prepaid Wallet")).to_contain_text("8 accounts")
    rail = kind(page, "Prepaid Wallet").locator("div").filter(has=page.get_by_role("link", name="Add account")).last
    assert rail.evaluate("el => el.scrollWidth > el.clientWidth + 1"), "eight cards run past a desktop's edge too"
    # Headless browsers hide every scrollbar, so the test reads the style that shows it rather than measuring it.
    assert rail.evaluate("el => getComputedStyle(el).scrollbarWidth") == "thin", "a scrollbar to drag"

    phone = browser.new_context(
        viewport={"width": 390, "height": 844}, base_url=server, reduced_motion="reduce", has_touch=True, is_mobile=True
    )
    try:
        touch = phone.new_page()
        touch.context.add_cookies(page.context.cookies())
        touch.goto("/accounts")
        expect(kind(touch, "Prepaid Wallet")).to_contain_text("8 accounts")
        rail = (
            kind(touch, "Prepaid Wallet").locator("div").filter(has=touch.get_by_role("link", name="Add account")).last
        )
        assert rail.evaluate("el => getComputedStyle(el).scrollbarWidth") == "none", (
            "a touch screen swipes, with no bar"
        )
    finally:
        phone.close()


def test_the_kinds_have_room_between_them_and_a_heading_larger_than_a_cards_name(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    nested(api, books)
    page.goto("/accounts")
    expect(kind(page, "Prepaid Wallet")).to_be_visible()
    size = page.locator("main h2").first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    name = kind(page, "Prepaid Wallet").get_by_role("link", name=re.compile("HDFC")).locator("span").first
    assert size > name.evaluate("e => parseFloat(getComputedStyle(e).fontSize)") + 2
    gaps = page.locator("main section").evaluate_all(
        "els => els.slice(1).map((e, i) => Math.round(e.getBoundingClientRect().top - els[i].getBoundingClientRect().bottom))"
    )
    assert gaps and min(gaps) >= 24, f"space between kinds: {gaps}"


def test_a_card_opens_the_account_and_the_add_card_opens_the_form_on_that_kind(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    nested(api, books)
    page.goto("/accounts")
    expect(kind(page, "Prepaid Wallet").get_by_role("link", name="Add account")).to_have_attribute(
        "href", "/accounts/new?type=assets.wallet"
    )
    kind(page, "Prepaid Wallet").get_by_role("link", name=re.compile("HDFC")).click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    expect(page.get_by_role("heading", level=1, name="HDFC")).to_be_visible()


def test_every_open_account_shows_and_only_closed_ones_are_tucked_away(signed_in_page: Page, api: Api, books, session):
    page = signed_in_page
    old = api.post("/accounts/", name="Old Wallet", parent_id=books["roots"]["Assets"])
    closed = api.post("/accounts/", name="Old Card", parent_id=books["roots"]["Liabilities"])
    api.post(f"/accounts/{closed['id']}/close")
    table = Account.__table__
    session.exec(
        table.update().where(table.c.id == UUID(old["id"])).values(created=datetime.now(UTC) - timedelta(days=30))
    )
    session.commit()
    page.goto("/accounts")
    expect(page.get_by_role("link", name=re.compile("Old Wallet"))).to_be_visible()
    assert "Old Card" not in cards(page)
    page.get_by_role("button", name="Load more").click()
    expect(page.get_by_role("link", name=re.compile("Old Card"))).to_contain_text("closed")
    expect(page.get_by_role("button", name="Load more")).to_have_count(0)


def test_closing_an_account_from_its_page(signed_in_page: Page, books):
    page = signed_in_page
    page.goto(f"/accounts/{books['cash']['id']}")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_label("More actions").click()
    page.get_by_role("button", name="Close account").click()
    page.wait_for_url(re.compile(r"/accounts$"))
    expect(page.get_by_text("Account closed")).to_be_visible()
    expect(page.get_by_role("link", name=re.compile("Checking"))).to_be_visible()
    assert "Cash" not in cards(page)
    page.get_by_role("button", name="Load more").click()
    expect(page.get_by_role("link", name=re.compile("^Cash closed"))).to_be_visible()


def test_the_cards_of_a_row_are_the_same_size(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    nested(api, books)
    page.goto("/accounts")
    expect(kind(page, "Prepaid Wallet")).to_be_visible()
    sizes = page.locator("main section a[href^='/accounts/']:not([href*='new'])").evaluate_all(
        "els => els.filter(e => !e.closest('h2')).map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)].join('x') })"
    )
    assert len(sizes) >= 4 and len(set(sizes)) == 1, sizes


def test_edit_on_an_account_is_in_its_menu(signed_in_page: Page, books):
    page = signed_in_page
    page.goto(f"/accounts/{books['checking']['id']}")
    page.get_by_label("More actions").click()
    expect(page.get_by_role("link", name="Edit", exact=True)).to_have_attribute(
        "href", f"/accounts/{books['checking']['id']}/edit"
    )


def test_load_more_loads_the_next_chunk_in_place(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    for i in range(70):
        api.post(
            "/transactions/",
            payee=f"Shop {i:02d}",
            date=str(date.today() - timedelta(days=1 + i)),
            postings=[leg(books["food"], "debit", "5"), leg(books["checking"], "credit", "5")],
        )
    page.goto(f"/accounts/{books['checking']['id']}")
    rows = page.get_by_role("button", name=re.compile(r"^Shop \d\d"))
    expect(rows.first).to_be_visible()
    first = rows.count()
    assert 25 <= first <= 35, first
    expect(page.get_by_text("Shop 69")).to_have_count(0)
    page.get_by_role("button", name="Load more").click()
    expect(rows).not_to_have_count(first)
    page.get_by_role("button", name="Load more").click()
    expect(page.get_by_role("button", name="Load more")).to_have_count(0)
    expect(page.get_by_text("Shop 69")).to_be_visible()
    assert rows.count() == 70, "every entry once"


def test_going_back_from_an_account_lands_on_the_accounts_page(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    api.post("/accounts/", name="Visa Gold", type="liabilities.cards", balance="50")
    page.goto("/accounts")
    page.get_by_role("link", name=re.compile("Visa Gold")).click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    expect(page.locator("header p").first).to_have_text("Credit Card")
    page.locator("main").get_by_role("link", name="Accounts").click()
    page.wait_for_url(re.compile(r"/accounts$"))


def test_saving_an_entry_started_from_an_accounts_page_comes_back_to_it(signed_in_page: Page, books):
    page = signed_in_page
    account = books["checking"]["id"]
    page.goto(f"/accounts/{account}")
    expect(page.get_by_role("heading", level=1, name="Checking")).to_be_visible()
    page.get_by_role("navigation", name="Tab bar").get_by_role("link", name="New transaction").click()
    page.wait_for_url(re.compile(r"/transactions/new"))
    page.get_by_label("Amount", exact=True).fill("75")
    page.get_by_role("button", name=re.compile("^Spent on")).click()
    page.get_by_role("dialog", name="Spent on").get_by_role("button", name=re.compile("Groceries")).first.click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(rf"/accounts/{account}$"))
    expect(page.get_by_role("button", name=re.compile("Groceries")).first).to_be_visible()


def test_editing_an_entry_from_an_accounts_page_comes_back_to_it(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    account = books["checking"]["id"]
    api.post(
        "/transactions/",
        payee="Corner shop",
        date=str(local_today()),
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
    )
    page.goto(f"/accounts/{account}")
    page.get_by_role("button", name=re.compile("^Corner shop")).click()
    page.get_by_role("dialog").get_by_role("link", name="Edit", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions/.+/edit\?back="))
    page.get_by_label("Amount", exact=True).fill("45")
    page.get_by_role("button", name="Save changes", exact=True).click()
    page.wait_for_url(re.compile(rf"/accounts/{account}$"))
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_the_pin_button_lists_the_account_in_a_pinned_row_at_the_top(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    nested(api, books)
    hdfc = next(a for a in api.get("/accounts/") if a["name"] == "HDFC")
    page.goto(f"/accounts/{hdfc['id']}")
    page.get_by_role("button", name="Pin to top").click()
    expect(page.get_by_role("button", name="Unpin")).to_be_visible()
    page.goto("/accounts")
    expect(page.locator("main h2").first).to_have_text("Pinned")
    kind(page, "Pinned").get_by_role("link", name=re.compile("HDFC")).click()
    page.get_by_role("button", name="Unpin").click()
    expect(page.get_by_role("button", name="Pin to top")).to_be_visible()
    page.goto("/accounts")
    expect(page.locator("main h2").first).not_to_have_text("Pinned")


def test_the_description_opens_from_the_i_and_gives_way_to_the_menu(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    checking = books["checking"]
    response = page.request.patch(
        f"/api/accounts/{checking['id']}", data={"details": "The salary account"}, headers=api.headers
    )
    assert response.ok, response.text()
    page.goto(f"/accounts/{checking['id']}")
    note = page.get_by_text("The salary account")
    expect(note).to_be_hidden()
    page.get_by_label("About Checking").click()
    expect(note).to_be_visible()
    page.get_by_label("More actions").click()
    expect(note).to_be_hidden()
    expect(page.get_by_role("button", name="Close account")).to_be_visible()
    page.get_by_label("About Checking").click()
    expect(note).to_be_visible()
    expect(page.get_by_role("button", name="Close account")).to_be_hidden()


def test_no_description_means_no_i(signed_in_page: Page, books):
    page = signed_in_page
    page.goto(f"/accounts/{books['cash']['id']}")
    expect(page.get_by_role("heading", level=1, name="Cash")).to_be_visible()
    expect(page.get_by_label("About Cash")).to_have_count(0)


def test_pay_bill_opens_the_form_with_the_card_and_the_amount(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    card = api.post("/accounts/", name="Amex", parent_id=books["roots"]["Liabilities"], statement_day=1, due_day=20)
    api.post(
        "/transactions/",
        payee="Flights",
        date=str(local_today() - timedelta(days=75)),
        postings=[leg(books["food"], "debit", "1250"), leg(card, "credit", "1250")],
    )
    page.goto(f"/accounts/{card['id']}")
    expect(page.get_by_role("region", name="Bill")).to_contain_text("1,250.00")
    page.get_by_role("link", name="Pay bill").click()
    page.wait_for_url(re.compile(r"/transactions/new"))
    expect(page.get_by_label("Amount", exact=True)).to_have_value("1,250.00")
    expect(page.get_by_role("button", name=re.compile("^To(?! do)"))).to_contain_text("Amex")


def test_an_empty_page_shows_the_four_types_and_each_adds_an_account_of_its_type(signed_in_page: Page):
    page = signed_in_page
    page.goto("/accounts")
    expect(page.locator("main h2")).to_have_text(["Bank Account", "Cash", "Credit Card", "Prepaid Wallet"])
    expect(kind(page, "Prepaid Wallet").get_by_role("link", name="Add account")).to_have_attribute(
        "href", "/accounts/new?type=assets.wallet"
    )
    kind(page, "Prepaid Wallet").get_by_role("link", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/new\?type=assets.wallet$"))
    expect(page.get_by_role("radio", name="Prepaid Wallet")).to_have_attribute("aria-checked", "true")


# ---- the account form ----------------------------------------------------------------------------------


def chip(page: Page, name: str):
    return page.get_by_role("radiogroup", name="Kind of account").get_by_role("radio", name=name, exact=True)


def test_the_days_are_asked_only_for_a_credit_card(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/accounts/new")
    days = page.get_by_label("Statement day")
    expect(chip(page, "Credit Card")).to_be_visible()
    expect(days).to_have_count(0)
    chip(page, "Credit Card").click()
    expect(days).to_be_visible()
    chip(page, "Bank Account").click()
    expect(days).to_have_count(0)
    chip(page, "Credit Card").click()
    page.get_by_label("Name").fill("Amex")
    page.get_by_label("Statement day").fill("10")
    page.get_by_label("Payment due day").fill("28")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    expect(page.get_by_role("region", name="Bill")).to_contain_text("Nothing due")


def test_a_new_account_without_a_kind_is_told_to_choose_one(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/accounts/new")
    page.get_by_label("Name").fill("Nowhere")
    page.get_by_role("button", name="Add account").click()
    expect(page.get_by_role("alert")).to_contain_text("kind")
