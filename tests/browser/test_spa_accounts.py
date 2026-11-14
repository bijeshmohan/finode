"""The React app's Accounts page and an account's page in a browser (ports of test_accounts_page.py,
test_account_info.py, test_card_bills.py and test_fixed_parents.py)."""

import re
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from playwright.sync_api import Page, expect

from app.clock import local_today
from app.models.account import Account
from app.services import account as account_service

from ..books import leg
from .conftest import Api


def cards(page: Page) -> list[str]:
    """The names on the account cards that are shown."""
    return page.locator("main section a[href^='/accounts/']:not([href*='new'])").evaluate_all(
        "els => els.filter(e => !e.closest('h2')).map(e => e.querySelector('span > span').textContent)"
    )


def kind(page: Page, name: str):
    return page.locator("main section").filter(has=page.get_by_role("heading", name=name, exact=True))


def nested(api: Api, books):
    banks = api.post("/accounts/", name="Banks", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="HDFC", parent_id=banks["id"], balance="100")
    api.post("/accounts/", name="SBI", parent_id=banks["id"], balance="50")
    savings = api.post("/accounts/", name="Savings", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="Rainy", parent_id=savings["id"])
    return banks, savings


def test_every_kind_is_a_row_of_cards_under_its_heading(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    nested(spa_api, spa_books)
    page.goto("/accounts")
    expect(kind(page, "Banks")).to_contain_text("2 accounts")
    assert {"HDFC", "SBI", "Rainy", "Checking", "Cash"} <= set(cards(page))
    assert "Opening Balances" not in cards(page), "Equity is not listed"
    assert page.locator("main details").count() == 0, "nothing folds"
    expect(page.locator("main h2").first).to_have_text("Banks")


def test_a_long_row_scrolls_sideways_on_its_own_and_the_page_does_not(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    long = spa_api.post("/accounts/", name="Wallets", parent_id=spa_books["roots"]["Assets"])
    for number in range(8):
        spa_api.post("/accounts/", name=f"Wallet {number}", parent_id=long["id"])
    short = spa_api.post("/accounts/", name="Funds", parent_id=spa_books["roots"]["Assets"])
    spa_api.post("/accounts/", name="Fund A", parent_id=short["id"])
    page.goto("/accounts")
    wallets, funds = kind(page, "Wallets"), kind(page, "Funds")
    expect(wallets).to_contain_text("8 accounts")
    rail = wallets.locator("div").filter(has=page.get_by_role("link", name="Add account")).last
    assert rail.evaluate("el => el.scrollWidth > el.clientWidth + 1"), "eight cards run past the edge"
    assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    rail.evaluate("el => { el.scrollLeft = el.scrollWidth }")
    assert rail.evaluate("el => el.scrollLeft") > 0
    funds_rail = funds.locator("div").filter(has=page.get_by_role("link", name="Add account")).last
    assert funds_rail.evaluate("el => el.scrollLeft") == 0


def test_the_kinds_have_room_between_them_and_a_heading_larger_than_a_cards_name(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    nested(spa_api, spa_books)
    page.goto("/accounts")
    expect(kind(page, "Banks")).to_be_visible()
    size = page.locator("main h2").first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    name = kind(page, "Banks").get_by_role("link", name=re.compile("HDFC")).locator("span").first
    assert size > name.evaluate("e => parseFloat(getComputedStyle(e).fontSize)") + 2
    gaps = page.locator("main section").evaluate_all(
        "els => els.slice(1).map((e, i) => Math.round(e.getBoundingClientRect().top - els[i].getBoundingClientRect().bottom))"
    )
    assert gaps and min(gaps) >= 24, f"space between kinds: {gaps}"


def test_a_card_opens_the_account_and_the_add_card_opens_the_form_on_that_kind(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    banks, _ = nested(spa_api, spa_books)
    page.goto("/accounts")
    expect(kind(page, "Banks").get_by_role("link", name="Add account")).to_have_attribute(
        "href", f"/accounts/new?parent={banks['id']}"
    )
    kind(page, "Banks").get_by_role("link", name=re.compile("HDFC")).click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    expect(page.get_by_role("heading", level=1, name="HDFC")).to_be_visible()


def test_every_open_account_shows_and_only_closed_ones_are_tucked_away(
    signed_in_spa_page: Page, spa_api: Api, spa_books, session
):
    page = signed_in_spa_page
    old = spa_api.post("/accounts/", name="Old Wallet", parent_id=spa_books["roots"]["Assets"])
    closed = spa_api.post("/accounts/", name="Old Card", parent_id=spa_books["roots"]["Liabilities"])
    spa_api.post(f"/accounts/{closed['id']}/close")
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


def test_closing_an_account_from_its_page(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto(f"/accounts/{spa_books['cash']['id']}")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_label("More actions").click()
    page.get_by_role("button", name="Close account").click()
    page.wait_for_url(re.compile(r"/accounts$"))
    expect(page.get_by_text("Account closed")).to_be_visible()
    expect(page.get_by_role("link", name=re.compile("Checking"))).to_be_visible()
    assert "Cash" not in cards(page)
    page.get_by_role("button", name="Load more").click()
    expect(page.get_by_role("link", name=re.compile("^Cash"))).to_be_visible()


def test_the_cards_of_a_row_are_the_same_size(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    nested(spa_api, spa_books)
    page.goto("/accounts")
    expect(kind(page, "Banks")).to_be_visible()
    sizes = page.locator("main section a[href^='/accounts/']:not([href*='new'])").evaluate_all(
        "els => els.filter(e => !e.closest('h2')).map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)].join('x') })"
    )
    assert len(sizes) >= 4 and len(set(sizes)) == 1, sizes


def test_edit_on_an_account_is_in_its_menu(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto(f"/accounts/{spa_books['checking']['id']}")
    page.get_by_label("More actions").click()
    expect(page.get_by_role("link", name="Edit", exact=True)).to_have_attribute(
        "href", f"/accounts/{spa_books['checking']['id']}/edit"
    )


def test_load_more_loads_the_next_chunk_in_place(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    for i in range(70):
        spa_api.post(
            "/transactions/",
            payee=f"Shop {i:02d}",
            date=str(date.today() - timedelta(days=1 + i)),
            postings=[leg(spa_books["food"], "debit", "5"), leg(spa_books["checking"], "credit", "5")],
        )
    page.goto(f"/accounts/{spa_books['checking']['id']}")
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


def test_going_back_from_an_account_lands_on_the_accounts_page(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    group = spa_api.post("/accounts/", name="Cards", parent_id=spa_books["roots"]["Liabilities"])
    spa_api.post("/accounts/", name="Visa Gold", parent_id=group["id"], balance="50")
    page.goto("/accounts")
    page.get_by_role("link", name=re.compile("Visa Gold")).click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    expect(page.locator("header p").first).to_have_text("Cards")
    page.locator("main").get_by_role("link", name="Accounts").click()
    page.wait_for_url(re.compile(r"/accounts$"))


def test_saving_an_entry_started_from_an_accounts_page_comes_back_to_it(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    account = spa_books["checking"]["id"]
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


def test_a_groups_heading_opens_its_page_with_its_accounts_in_a_row_and_their_transactions(
    signed_in_spa_page: Page, spa_api: Api, spa_books
):
    page = signed_in_spa_page
    banks, _ = nested(spa_api, spa_books)
    hdfc = next(a for a in spa_api.get("/accounts/") if a["name"] == "HDFC")
    spa_api.post(
        "/transactions/",
        payee="Gadget Store",
        postings=[leg(spa_books["cash"], "debit", "10"), leg(hdfc, "credit", "10")],
    )
    page.goto("/accounts")
    kind(page, "Banks").get_by_role("link", name="Banks", exact=True).click()
    expect(page).to_have_url(re.compile(rf"/accounts/{banks['id']}$"))
    expect(page.get_by_role("heading", name="Accounts", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name=re.compile("^(HDFC|SBI)"))).to_have_count(2)
    expect(page.get_by_role("link", name="Add account")).to_have_attribute(
        "href", f"/accounts/new?parent={banks['id']}"
    )
    expect(page.get_by_role("heading", name="Transactions")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Gadget Store"))).to_contain_text("HDFC")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "only the row scrolls sideways"
    page.get_by_role("link", name=re.compile("^SBI")).click()
    expect(page.get_by_role("heading", level=1, name="SBI")).to_be_visible()


def test_the_pin_button_lists_the_account_in_a_pinned_row_at_the_top(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    nested(spa_api, spa_books)
    hdfc = next(a for a in spa_api.get("/accounts/") if a["name"] == "HDFC")
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


def test_the_description_opens_from_the_i_and_gives_way_to_the_menu(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    checking = spa_books["checking"]
    response = page.request.patch(
        f"/api/accounts/{checking['id']}", data={"details": "The salary account"}, headers=spa_api.headers
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


def test_no_description_means_no_i(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto(f"/accounts/{spa_books['cash']['id']}")
    expect(page.get_by_role("heading", level=1, name="Cash")).to_be_visible()
    expect(page.get_by_label("About Cash")).to_have_count(0)


def test_pay_bill_opens_the_form_with_the_card_and_the_amount(signed_in_spa_page: Page, spa_api: Api, spa_books):
    page = signed_in_spa_page
    card = spa_api.post(
        "/accounts/", name="Amex", parent_id=spa_books["roots"]["Liabilities"], statement_day=1, due_day=20
    )
    spa_api.post(
        "/transactions/",
        payee="Flights",
        date=str(local_today() - timedelta(days=75)),
        postings=[leg(spa_books["food"], "debit", "1250"), leg(card, "credit", "1250")],
    )
    page.goto(f"/accounts/{card['id']}")
    expect(page.get_by_role("region", name="Bill")).to_contain_text("1,250.00")
    page.get_by_role("link", name="Pay bill").click()
    page.wait_for_url(re.compile(r"/transactions/new"))
    expect(page.get_by_label("Amount", exact=True)).to_have_value("1,250.00")
    expect(page.get_by_role("button", name=re.compile("^To"))).to_contain_text("Amex")


@pytest.fixture
def with_groups(monkeypatch):
    """A new profile gets the five built-in groups (asked for before the person signs in, as their books start then)."""
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)


def test_an_empty_page_shows_the_five_shelves_and_each_adds_an_account_of_its_kind(
    with_groups, signed_in_spa_page: Page
):
    page = signed_in_spa_page
    page.goto("/accounts")
    expect(page.locator("main h2")).to_have_text(["Bank Accounts", "Cash", "Credit Cards", "Investments", "Loans"])
    expect(kind(page, "Bank Accounts").get_by_role("link", name="Add account")).to_have_attribute(
        "href", re.compile(r"/accounts/new\?parent=")
    )
