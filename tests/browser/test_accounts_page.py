"""The accounts page in a browser: groups under their headings, the recent cards, search, unused and closed accounts."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from playwright.sync_api import Page, expect

from app.models.account import Account

from .conftest import Api


def visible(page: Page) -> list[str]:
    return page.eval_on_selector_all(
        "[data-accounts] li[data-path]",
        "els => els.filter(e => e.checkVisibility() && !e.closest('details:not([open])')).map(e => e.dataset.path)",
    )


def nested(api: Api, books):
    banks = api.post("/accounts/", name="Banks", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="HDFC", parent_id=banks["aid"], balance="100")
    api.post("/accounts/", name="SBI", parent_id=banks["aid"], balance="50")
    food = api.post("/accounts/", name="Savings", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="Rainy", parent_id=food["aid"])
    return banks, food


def test_every_group_is_open_under_its_heading_and_only_equity_folds(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    shown = visible(page)
    assert "assets › banks › hdfc" in shown and "assets › savings › rainy" in shown and "assets › checking" in shown
    assert "equity › opening balances" not in shown, "Equity starts folded to one line"
    assert page.locator("details").count() == 1 and page.locator("[data-section]").count() == 3
    page.locator("details.equity > summary").click()
    assert "equity › opening balances" in visible(page)


def test_a_groups_heading_goes_to_its_page(page: Page, api, books):
    banks, _ = nested(api, books)
    page.goto("/accounts")
    page.locator(f'a.acc-gh[href="/accounts/{banks["aid"]}"]').click()
    page.wait_for_url(f"**/accounts/{banks['aid']}")
    expect(page.get_by_role("heading", name="Banks")).to_be_visible()


def test_searching_finds_accounts_inside_closed_groups(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    page.fill("[data-account-search]", "rain")
    assert visible(page) == ["assets › savings › rainy"]
    expect(page.locator("a.acc-gh", has_text="Savings")).to_be_visible()
    expect(page.locator("a.acc-gh", has_text="Banks")).to_be_hidden()
    page.fill("[data-account-search]", "zzz")
    expect(page.locator("[data-no-match]")).to_be_visible()
    page.fill("[data-account-search]", "")
    assert "assets › banks › hdfc" in visible(page), "clearing the search puts the layout back"


def test_unused_and_closed_accounts_are_tucked_away(page: Page, api, books, session):
    old = api.post("/accounts/", name="Old Wallet", parent_id=books["roots"]["Assets"])
    closed = api.post("/accounts/", name="Old Card", parent_id=books["roots"]["Liabilities"])
    api.request.post(f"/api/accounts/{closed['aid']}/close")
    table = Account.__table__
    session.exec(table.update().where(table.c.aid == UUID(old["aid"])).values(created=datetime.now(timezone.utc) - timedelta(days=30)))
    session.commit()
    page.goto("/accounts")
    assert "assets › old wallet" not in visible(page) and "liabilities › old card" not in visible(page)
    page.get_by_role("button", name="1 unused account hidden").click()
    assert "assets › old wallet" in visible(page)
    page.get_by_role("button", name="1 closed account").click()
    assert "liabilities › old card" in visible(page)
    expect(page.locator("li", has_text="Old Card").locator(".badge")).to_have_text("closed")


def test_closing_an_account_from_its_page(page: Page, api, books):
    page.goto(f"/accounts/{books['cash']['aid']}")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_label("More actions").click()
    page.get_by_role("button", name="Close account").click()
    page.wait_for_url("**/accounts")
    assert "assets › cash" not in visible(page)
    page.get_by_role("button", name="1 closed account").click()
    assert "assets › cash" in visible(page)


def test_recently_used_accounts_are_cards_that_the_search_hides(page: Page, api, books):
    banks, _ = nested(api, books)
    hdfc = next(a for a in api.get("/accounts/") if a["name"] == "HDFC")
    api.post("/transactions/", date="2026-01-05", postings=[
        {"account": hdfc["aid"], "side": "debit", "amount": "5"}, {"account": books["cash"]["aid"], "side": "credit", "amount": "5"}])
    page.goto("/accounts")
    card = page.locator("a.card-acc", has_text="HDFC")
    expect(card).to_be_visible()
    expect(card.locator(".ca-cap")).to_have_text("Banks")
    page.locator("[data-account-search]").fill("hdfc")
    expect(page.locator(".recent-cards")).to_be_hidden()
    page.locator("[data-account-search]").fill("")
    expect(page.locator(".recent-cards")).to_be_visible()


def test_moving_an_account_changes_the_order_on_the_page(page: Page, api, books):
    banks, _ = nested(api, books)
    sbi = next(a for a in api.get("/accounts/") if a["name"] == "SBI")
    page.goto(f"/accounts/{sbi['aid']}")
    page.get_by_label("More actions").click()
    page.get_by_role("button", name="Move up").click()
    page.get_by_label("More actions").click()
    expect(page.get_by_role("button", name="A–Z")).to_be_visible()
    page.goto("/accounts")
    names = page.locator("li[data-path^='assets › banks › '] .account-name").all_inner_texts()
    assert [n.split()[0] for n in names] == ["SBI", "HDFC"]


def test_names_and_amounts_line_up_in_every_row(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    rights = page.eval_on_selector_all(
        ".account-row .account-balance",
        "els => els.filter(e => e.checkVisibility()).map(e => Math.round(e.getBoundingClientRect().right))",
    )
    lefts = page.eval_on_selector_all(
        ".account-row .account-name",
        "els => els.filter(e => e.checkVisibility()).map(e => Math.round(e.getBoundingClientRect().left))",
    )
    assert len(rights) >= 5 and len(set(rights)) == 1, f"amounts end at the same edge: {rights}"
    assert len(lefts) >= 5 and len(set(lefts)) == 1, f"names start at the same edge: {lefts}"


def test_the_edit_button_on_an_account_is_one_tap_away(page: Page, books):
    page.goto(f"/accounts/{books['checking']['aid']}")
    page.get_by_role("link", name="Edit Checking").click()
    page.wait_for_url(f"**/accounts/{books['checking']['aid']}/edit")
