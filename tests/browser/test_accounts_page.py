"""The accounts page in a browser: a row of cards under each kind, its count and track, closed accounts."""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from playwright.sync_api import Page, expect

from app.models.account import Account

from ..books import leg
from .conftest import Api


def cards(page: Page) -> list[str]:
    """The names on the cards that can be seen (a closed account's card is hidden until Load more)."""
    return page.eval_on_selector_all(
        "[data-accounts] a.acc-card:not(.acc-card-add)",
        "els => els.filter(e => e.checkVisibility()).map(e => e.querySelector('.acc-card-name > span').textContent)",
    )


def nested(api: Api, books):
    banks = api.post("/accounts/", name="Banks", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="HDFC", parent_id=banks["id"], balance="100")
    api.post("/accounts/", name="SBI", parent_id=banks["id"], balance="50")
    food = api.post("/accounts/", name="Savings", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="Rainy", parent_id=food["id"])
    return banks, food


def test_every_kind_is_a_row_of_cards_under_its_heading(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    assert {"HDFC", "SBI", "Rainy", "Checking", "Cash"} <= set(cards(page))
    assert "Opening Balances" not in cards(page), "Equity is not listed"
    expect(page.locator(".cat-chips")).to_have_count(0)
    assert page.locator("details").count() == 0, "nothing folds"
    expect(page.locator(".acc-gh > span:first-child").first).to_contain_text("Banks")


def test_a_row_that_runs_past_the_screen_shows_its_count_and_a_track_and_a_short_one_shows_neither(
    page: Page, api, books
):
    long = api.post("/accounts/", name="Wallets", parent_id=books["roots"]["Assets"])
    for number in range(8):
        api.post("/accounts/", name=f"Wallet {number}", parent_id=long["id"])
    short = api.post("/accounts/", name="Funds", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="Fund A", parent_id=short["id"])
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto("/accounts")
    wallets = page.locator(".acc-kind", has_text="Wallets")
    funds = page.locator(".acc-kind", has_text="Funds")
    expect(wallets.locator("[data-count]")).to_have_text("8")
    expect(wallets.locator("[data-track]")).to_be_visible()
    expect(funds.locator("[data-count]")).to_be_hidden()
    expect(funds.locator("[data-track]")).to_be_hidden()
    bar = wallets.locator("[data-track] i")
    before = bar.bounding_box()["x"]
    wallets.locator("[data-rail]").evaluate("el => { el.scrollLeft = el.scrollWidth }")
    page.wait_for_function(
        "(b) => [...document.querySelectorAll('.acc-kind')].find((k) => k.textContent.includes('Wallets'))"
        ".querySelector('[data-track] i').getBoundingClientRect().x > b",
        arg=before,
    )


def test_a_card_opens_the_account_and_the_add_card_opens_the_form_on_that_kind(page: Page, api, books):
    banks, _ = nested(api, books)
    page.goto("/accounts")
    page.locator(".acc-card-add").first.click()
    page.wait_for_url(f"**/accounts/new?parent={banks['id']}")
    expect(page.locator("[data-kind-chip][aria-pressed='true']")).to_have_text("Banks")
    page.go_back()
    page.locator("a.acc-card", has_text="HDFC").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))


def test_every_open_account_shows_and_only_closed_ones_are_tucked_away(page: Page, api, books, session):
    old = api.post("/accounts/", name="Old Wallet", parent_id=books["roots"]["Assets"])
    closed = api.post("/accounts/", name="Old Card", parent_id=books["roots"]["Liabilities"])
    api.request.post(f"/api/accounts/{closed['id']}/close")
    table = Account.__table__
    session.exec(
        table.update().where(table.c.id == UUID(old["id"])).values(created=datetime.now(UTC) - timedelta(days=30))
    )
    session.commit()
    page.goto("/accounts")
    assert "Old Wallet" in cards(page), "no entries, no balance and old: still listed"
    assert "Old Card" not in cards(page)
    page.get_by_role("button", name="Load more").click()
    assert "Old Card" in cards(page)
    expect(page.get_by_role("button", name="Load more")).to_have_count(0)
    expect(page.locator("a.acc-card", has_text="Old Card").locator(".badge")).to_have_text("closed")


def test_closing_an_account_from_its_page(page: Page, api, books):
    page.goto(f"/accounts/{books['cash']['id']}")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_label("More actions").click()
    page.get_by_role("button", name="Close account").click()
    page.wait_for_url("**/accounts")
    assert "Cash" not in cards(page)
    page.get_by_role("button", name="Load more").click()
    assert "Cash" in cards(page)


def test_the_cards_of_a_row_are_the_same_size(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    sizes = page.eval_on_selector_all(
        "a.acc-card:not(.acc-card-add)",
        "els => els.filter(e => e.checkVisibility()).map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)].join('x') })",
    )
    assert len(sizes) >= 4 and len(set(sizes)) == 1, sizes


def test_edit_on_an_account_is_in_its_menu(page: Page, books):
    page.goto(f"/accounts/{books['checking']['id']}")
    page.get_by_label("More actions").click()
    page.get_by_role("link", name="Edit", exact=True).click()
    page.wait_for_url(f"**/accounts/{books['checking']['id']}/edit")


def test_show_earlier_loads_the_next_chunk_in_place(page: Page, books, api: Api):
    from datetime import date, timedelta

    for i in range(70):
        api.post(
            "/transactions/",
            payee=f"Shop {i:02d}",
            date=str(date.today() - timedelta(days=1 + i)),
            postings=[
                leg(books["food"], "debit", "5"),
                leg(books["checking"], "credit", "5"),
            ],
        )
    page.goto(f"/accounts/{books['checking']['id']}")
    rows = page.locator("a.tx")
    first = rows.count()
    assert 25 <= first <= 35, first
    expect(page.get_by_text("Shop 69")).to_have_count(0)
    button = page.get_by_role("button", name="Load more")
    button.click()
    expect(rows).not_to_have_count(first)
    assert rows.count() > first + 25
    expect(page.get_by_text("Shop 00")).to_be_visible()
    page.get_by_role("button", name="Load more").click()
    expect(page.get_by_role("button", name="Load more")).to_have_count(0)
    expect(page.get_by_text("Shop 69")).to_be_visible()


def test_the_new_account_form_asks_about_the_budget_by_its_kind(page: Page, api, books):
    banks = api.post("/accounts/", name="Banks", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="HDFC", parent_id=banks["id"])
    loans = api.post("/accounts/", name="Loans", parent_id=books["roots"]["Liabilities"])
    api.post("/accounts/", name="Old loan", parent_id=loans["id"])
    page.goto("/accounts/new")
    fields = page.locator("[data-budget-fields]")
    expect(fields).to_be_hidden()  # no kind chosen yet
    expect(page.locator("[data-kind-chip][aria-pressed='true']")).to_have_count(0)
    box = page.locator('input[name="on_budget"]')
    label = page.locator("[data-balance-label]")
    kind = page.locator("[data-kind-chip]")
    kind.filter(has_text="Banks").click()
    expect(fields).to_be_visible()
    expect(box).to_be_checked()
    expect(label).to_have_text("Current balance")
    kind.filter(has_text="Loans").click()
    expect(box).not_to_be_checked()  # a loan or card starts outside the budget
    expect(label).to_have_text("Amount you owe now")
    expect(kind.filter(has_text="Loans")).to_have_attribute("aria-pressed", "true")
    expect(kind.filter(has_text="Banks")).to_have_attribute("aria-pressed", "false")
    page.locator('input[name="name"]').fill("Car loan")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))  # not /accounts/new, where the form already is
    loan = next(a for a in api.get("/accounts/") if a["name"] == "Car loan")
    assert loan["on_budget"] is False and loan["parent_id"] == loans["id"]


def test_the_budget_box_works_when_the_form_opens_on_a_type_or_a_kind(page: Page, api, books):
    for url in ("/accounts/new?root=assets", f"/accounts/new?parent={books['checking']['id']}"):
        page.goto(url)
        box = page.locator('input[name="on_budget"]')
        expect(box).to_be_checked()
        box.uncheck()
        expect(box).not_to_be_checked()


def test_going_back_from_an_account_lands_on_the_accounts_page(page: Page, api, books):
    cards_group = api.post("/accounts/", name="Cards", parent_id=books["roots"]["Liabilities"])
    api.post("/accounts/", name="Visa Gold", parent_id=cards_group["id"], balance="50")
    page.goto("/accounts")
    page.locator("a.acc-card", has_text="Visa Gold").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    expect(page.locator(".acct-sub")).to_have_text("Cards")
    page.locator("a.back").click()
    page.wait_for_url("**/accounts")


def test_saving_an_entry_started_from_an_accounts_page_comes_back_to_it(page: Page, api, books):
    account = books["checking"]["id"]
    page.goto(f"/accounts/{account}")
    page.locator("a.fab").click()  # the bar's plus, not the page's own Add button
    page.wait_for_url("**/transactions/new**")
    page.fill("#total", "75")
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(rf"/accounts/{account}$"))
    expect(page.locator("a.tx", has_text="Groceries").first).to_be_visible()
