"""The accounts page in a browser: the type chips, groups under their headings and closed accounts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from playwright.sync_api import Page, expect

from app.models.account import Account

from .conftest import Api


def visible(page: Page) -> list[str]:
    return page.eval_on_selector_all(
        "[data-accounts] li[data-path]",
        "els => els.filter(e => e.checkVisibility() && !e.closest('details:not([open])')).map(e => e.dataset.path)",
    )


def open_options(page: Page) -> None:
    """The budget choices are folded away on the form; open them (the details element works even while its parent is hidden)."""
    page.evaluate("document.querySelectorAll('details.budget-options').forEach(d => d.open = true)")


def nested(api: Api, books):
    banks = api.post("/accounts/", name="Banks", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="HDFC", parent_id=banks["aid"], balance="100")
    api.post("/accounts/", name="SBI", parent_id=banks["aid"], balance="50")
    food = api.post("/accounts/", name="Savings", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="Rainy", parent_id=food["aid"])
    return banks, food


def test_every_group_is_open_under_its_heading_and_nothing_folds(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    shown = visible(page)
    assert "assets › banks › hdfc" in shown and "assets › savings › rainy" in shown and "assets › checking" in shown
    assert page.locator("details").count() == 0, "nothing folds, not even Equity"
    assert "equity › opening balances" not in shown, "Equity is not listed on the other chips"


def test_the_chips_switch_between_rows_and_the_chosen_one_leads_to_the_other_row(page: Page, api, books):
    nested(api, books)
    page.goto("/accounts")
    chips = page.locator(".cat-chips .chip")
    assert chips.all_inner_texts() == ["Asset", "Liability"]
    expect(chips.nth(0)).to_have_attribute("aria-pressed", "true")
    page.get_by_role("link", name="Liability").click()
    page.wait_for_url("**/accounts?tab=liabilities")
    shown = visible(page)
    assert shown == ["liabilities › visa"], shown
    expect(page.locator(".cat-chips .chip").nth(1)).to_have_attribute("aria-pressed", "true")
    page.get_by_role(
        "link", name="Liability"
    ).click()  # tapping the chosen chip again swaps the row: Expense, Equity (chosen) and Income
    page.wait_for_url("**/accounts?tab=equity")
    assert visible(page) == ["equity › opening balances"]
    assert page.locator(".cat-chips .chip").all_inner_texts() == ["Expense", "Equity", "Income"]
    expect(page.locator(".cat-chips .chip[aria-pressed='true']")).to_have_text("Equity")
    page.get_by_role("link", name="Income").click()
    page.wait_for_url("**/accounts?tab=income")
    expect(page.locator(".cat-chips .chip[aria-pressed='true']")).to_have_text("Income")
    page.get_by_role("link", name="Income").click()  # the chosen chip again goes back to Asset and Liability
    page.wait_for_url("**/accounts?tab=assets")
    assert chips.all_inner_texts() == ["Asset", "Liability"]


def test_a_groups_heading_goes_to_its_page(page: Page, api, books):
    banks, _ = nested(api, books)
    page.goto("/accounts")
    page.locator(f'a.acc-gh[href="/accounts/{banks["aid"]}"]').click()
    page.wait_for_url(f"**/accounts/{banks['aid']}")
    expect(page.get_by_role("heading", name="Banks")).to_be_visible()


def test_every_open_account_shows_and_only_closed_ones_are_tucked_away(page: Page, api, books, session):
    old = api.post("/accounts/", name="Old Wallet", parent_id=books["roots"]["Assets"])
    closed = api.post("/accounts/", name="Old Card", parent_id=books["roots"]["Liabilities"])
    api.request.post(f"/api/accounts/{closed['aid']}/close")
    table = Account.__table__
    session.exec(
        table.update().where(table.c.aid == UUID(old["aid"])).values(created=datetime.now(UTC) - timedelta(days=30))
    )
    session.commit()
    page.goto("/accounts")
    assert "assets › old wallet" in visible(page), "no entries, no balance and old: still listed"
    page.goto("/accounts?tab=liabilities")
    assert "liabilities › old card" not in visible(page)
    page.get_by_role("button", name="Load more").click()
    assert "liabilities › old card" in visible(page)
    expect(page.get_by_role("button", name="Load more")).to_have_count(0)
    expect(page.locator("li", has_text="Old Card").locator(".badge")).to_have_text("closed")


def test_closing_an_account_from_its_page(page: Page, api, books):
    page.goto(f"/accounts/{books['cash']['aid']}")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_label("More actions").click()
    page.get_by_role("button", name="Close account").click()
    page.wait_for_url("**/accounts?tab=assets")
    assert "assets › cash" not in visible(page)
    page.get_by_role("button", name="Load more").click()
    assert "assets › cash" in visible(page)


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


def test_show_earlier_loads_the_next_chunk_in_place(page: Page, books, api: Api):
    from datetime import date, timedelta

    for i in range(70):
        api.post(
            "/transactions/",
            payee=f"Shop {i:02d}",
            date=str(date.today() - timedelta(days=1 + i)),
            postings=[
                {"account": books["food"]["aid"], "side": "debit", "amount": "5"},
                {"account": books["checking"]["aid"], "side": "credit", "amount": "5"},
            ],
        )
    page.goto(f"/accounts/{books['checking']['aid']}")
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


def test_the_new_account_form_asks_about_the_budget_by_where_it_belongs(page: Page, api, books):
    page.goto("/accounts/new")
    open_options(page)
    fields = page.locator("[data-budget-fields]")
    expect(fields).to_be_hidden()  # nothing chosen yet
    parent = page.locator('select[name="parent_id"]')
    box = page.locator('input[name="on_budget"]')
    payment = page.locator("[data-payment-category]")
    parent.select_option(label="Assets")
    expect(fields).to_be_visible()
    expect(box).to_be_checked()
    expect(payment).to_be_hidden()
    parent.select_option(label="Liabilities")
    expect(box).not_to_be_checked()
    expect(payment).to_be_visible()  # outside the budget: the expense category can be chosen
    parent.select_option(label="Equity")
    expect(fields).to_be_hidden()
    assert page.locator('[data-budget-fields] input[name="on_budget"]').is_disabled(), "hidden fields are not sent"
    parent.select_option(label="Liabilities")
    page.locator('input[name="name"]').fill("Car loan")
    page.locator('select[name="payment_category"]').select_option(label="Rent")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url("**/accounts/*")
    loan = next(a for a in api.get("/accounts/") if a["name"] == "Car loan")
    assert loan["on_budget"] is False and loan["payment_category_id"] == books["rent"]["aid"]


def test_the_budget_box_works_when_the_form_opens_on_a_type_or_a_group(page: Page, api, books):
    for url in ("/accounts/new?root=assets", f"/accounts/new?parent={books['checking']['aid']}"):
        page.goto(url)
        open_options(page)
        box = page.locator('input[name="on_budget"]')
        expect(box).to_be_checked()
        box.uncheck()
        expect(box).not_to_be_checked()
        expect(page.locator("[data-payment-category]")).to_be_visible()


def test_the_payment_category_shows_only_for_an_account_outside_the_budget(page: Page, api, books):
    page.goto("/accounts/new?root=assets")
    open_options(page)
    box = page.locator('input[name="on_budget"]')
    payment = page.locator("[data-payment-category]")
    expect(payment).to_be_hidden()  # an asset starts in the budget
    box.uncheck()
    expect(payment).to_be_visible()
    box.check()
    expect(payment).to_be_hidden()
    page.goto("/accounts/new")
    open_options(page)
    page.locator('select[name="parent_id"]').select_option(label="Liabilities")
    expect(payment).to_be_visible()  # a loan starts outside the budget


def test_going_back_from_an_account_keeps_the_chip(page: Page, api, books):
    cards = api.post("/accounts/", name="Cards", parent_id=books["roots"]["Liabilities"])
    api.post("/accounts/", name="Visa", parent_id=cards["aid"], balance="50")
    page.goto("/accounts")
    page.locator(".cat-chips .chip", has_text="Liability").click()
    page.wait_for_url("**/accounts?tab=liabilities")
    page.get_by_role("link", name="Cards").first.click()
    page.wait_for_url(f"**/accounts/{cards['aid']}")
    page.locator("a.back").click()
    page.wait_for_url("**/accounts?tab=liabilities")
    expect(page.locator(".cat-chips .chip[aria-pressed='true']")).to_have_text("Liability")


def test_budget_options_are_folded_and_say_where_the_account_stands(page: Page, api, books):
    page.goto("/accounts/new?root=assets")
    details = page.locator("details.budget-options")
    expect(details).to_be_visible()
    assert details.get_attribute("open") is None, "folded away at first"
    expect(page.locator("[data-budget-summary]")).to_have_text("Part of the budget")
    page.locator("details.budget-options summary").click()
    page.locator('input[name="on_budget"]').uncheck()
    expect(page.locator("[data-budget-summary]")).to_have_text("Outside the budget")
