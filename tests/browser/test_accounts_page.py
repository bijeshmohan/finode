"""The accounts page in a browser: what starts open, remembered choices, search, unused and closed accounts."""

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
    food = api.post("/accounts/", name="Food", parent_id=books["roots"]["Expenses"])
    api.post("/accounts/", name="Dining", parent_id=food["aid"])
    return banks, food


def test_assets_and_liabilities_start_open_and_the_other_types_folded(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    shown = visible(page)
    assert "assets › checking" in shown and "assets › banks" in shown
    assert "expenses › rent" not in shown, "Income, Equity and Expenses start folded to one line"
    assert "assets › banks › hdfc" not in shown, "groups start closed"
    assert page.locator("details.account-group[open]").count() == 2
    page.locator("details.account-group > summary", has_text="Expenses").click()
    assert "expenses › rent" in visible(page) and "expenses › food › dining" not in visible(page)


def test_opening_a_group_is_remembered_after_a_reload(page: Page, api, books):
    banks, _ = nested(api, books)
    page.goto("/accounts")
    page.locator(f'details[data-key="{banks["aid"]}"] > summary').click()
    assert "assets › banks › hdfc" in visible(page)
    page.reload()
    assert "assets › banks › hdfc" in visible(page), "still open after a reload"
    page.locator(f'details[data-key="{banks["aid"]}"] > summary').click()
    page.reload()
    assert "assets › banks › hdfc" not in visible(page), "closed again, and remembered"


def test_the_open_link_of_a_group_goes_to_its_page(page: Page, api, books):
    banks, _ = nested(api, books)
    page.goto("/accounts")
    page.locator(f'details[data-key="{banks["aid"]}"] > summary a.open-link').click()
    page.wait_for_url(f"**/accounts/{banks['aid']}")
    expect(page.get_by_role("heading", name="Banks")).to_be_visible()


def test_searching_finds_accounts_inside_closed_groups(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    page.fill("[data-account-search]", "dini")
    assert visible(page) == ["expenses › food", "expenses › food › dining"]
    page.fill("[data-account-search]", "zzz")
    expect(page.locator("[data-no-match]")).to_be_visible()
    page.fill("[data-account-search]", "")
    assert "assets › banks › hdfc" not in visible(page), "clearing the search puts the layout back"


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


def test_pinning_from_the_account_page_puts_it_at_the_top_of_the_list(page: Page, api, books):
    banks, _ = nested(api, books)
    hdfc = next(a for a in api.get("/accounts/") if a["name"] == "HDFC")
    page.goto(f"/accounts/{hdfc['aid']}")
    page.get_by_label("More actions").click()
    page.get_by_role("button", name="Pin", exact=True).click()
    page.get_by_label("More actions").click()
    expect(page.get_by_role("button", name="Unpin")).to_be_visible()
    page.goto("/accounts")
    quick = page.locator("[data-quick]").first
    expect(quick.locator(".gh")).to_have_text("Pinned")
    expect(quick.locator(".account-name")).to_contain_text("HDFC")
    expect(quick.locator(".path")).to_have_text("Assets › Banks")
    # searching shows the tree's own rows instead, so nothing appears twice
    page.locator("[data-account-search]").fill("hdfc")
    expect(page.locator("[data-quick]")).to_have_count(1)
    expect(page.locator("[data-quick]").first).to_be_hidden()
    page.locator("[data-account-search]").fill("")
    expect(page.locator("[data-quick]").first).to_be_visible()


def test_moving_an_account_changes_the_order_on_the_page(page: Page, api, books):
    banks, _ = nested(api, books)
    sbi = next(a for a in api.get("/accounts/") if a["name"] == "SBI")
    page.goto(f"/accounts/{sbi['aid']}")
    page.get_by_label("More actions").click()
    page.get_by_role("button", name="Move up").click()
    page.get_by_label("More actions").click()
    expect(page.get_by_role("button", name="A–Z")).to_be_visible()
    page.goto("/accounts")
    page.locator('details[data-key="%s"] > summary' % banks["aid"]).click()
    names = page.locator('details[data-key="%s"] li[data-path] .account-name' % banks["aid"]).all_inner_texts()
    assert [n.split()[0] for n in names] == ["SBI", "HDFC"]


def test_names_and_amounts_line_up_in_every_row(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    page.locator("details.account-group > summary", has_text="Expenses").click()
    rights = page.eval_on_selector_all(
        ".account-row .account-balance, .group-total",
        "els => els.filter(e => e.checkVisibility()).map(e => Math.round(e.getBoundingClientRect().right))",
    )
    lefts = page.eval_on_selector_all(
        ".account-row[style*='--depth: 0'] .account-name",
        "els => els.filter(e => e.checkVisibility()).map(e => Math.round(e.getBoundingClientRect().left))",
    )
    assert len(rights) >= 8 and len(set(rights)) == 1, f"amounts end at the same edge: {rights}"
    assert len(lefts) >= 4 and len(set(lefts)) == 1, f"names start at the same edge, groups and plain accounts alike: {lefts}"
