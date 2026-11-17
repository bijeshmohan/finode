"""The React app's Recurring list and form in a browser (ports of test_recurring_form.py and the recurring case of
test_posting_date.py): the form shares the Add screen's rows, and a split saves as one rule."""

import re

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def section(page: Page, title: str):
    return page.locator("section", has=page.get_by_role("heading", name=title, exact=True))


def rows(page: Page, title: str):
    return section(page, title).get_by_role("button", name=re.compile(f"^{title}"))


def pick(page: Page, title: str, index: int, label: str):
    rows(page, title).nth(index).click()
    page.get_by_role("dialog", name=title).get_by_role("button", name=re.compile(re.escape(label))).first.click()


def tune(page: Page, title: str, index: int, amount: str):
    section(page, title).get_by_role("button", name="Amount and date").nth(index).click()
    sheet = page.locator("dialog[open]")
    sheet.get_by_label("Amount", exact=True).fill(amount)
    sheet.get_by_role("button", name="Done").click()
    expect(sheet).to_have_count(0)


def save(page: Page):
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/recurring$"))


def a_rule(api: Api, books: dict, **extra) -> dict:
    return api.post(
        "/recurring/",
        from_account_id=books["checking"]["id"],
        to_account_id=books["roots"]["Expenses"],
        category_id=books["rent"]["id"],
        amount="900",
        frequency="monthly",
        start_date="2999-01-01",
        payee="Landlord",
        **extra,
    )


def test_a_split_rule_from_the_form(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    page.goto("/recurring/new")
    page.get_by_label("Amount", exact=True).fill("1000")
    pick(page, "Paid from", 0, "Checking")
    pick(page, "Spent on", 0, "Rent")
    tune(page, "Spent on", 0, "700")
    expect(rows(page, "Spent on")).to_have_count(2)
    expect(rows(page, "Spent on").nth(1)).to_contain_text("300.00 left")
    pick(page, "Spent on", 1, "Groceries")
    page.get_by_placeholder("Payee or Merchant?").fill("Landlord")
    save(page)
    expect(page.locator("main").get_by_role("link", name=re.compile("^Landlord"))).to_be_visible()
    [rule] = api.get("/recurring/")
    assert rule["from_account_id"] is None and len(rule["postings"]) == 3, "more than one account on a side is a split"


def test_a_plain_rule_stays_plain(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    page.goto("/recurring/new")
    page.get_by_label("Amount", exact=True).fill("500")
    pick(page, "Paid from", 0, "Checking")
    pick(page, "Spent on", 0, "Rent")
    page.get_by_label("Starts").fill("2999-01-01")
    save(page)
    [rule] = api.get("/recurring/")
    assert rule["from_account_id"] == books["checking"]["id"] and rule["postings"] == []
    assert rule["category_id"] == books["rent"]["id"]


def test_editing_a_rule_keeps_it_and_saves_the_change(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    rule = a_rule(api, books)
    page.goto(f"/recurring/{rule['id']}/edit")
    expect(page.get_by_label("Amount", exact=True)).to_have_value("900.00")
    expect(page.get_by_text(re.compile(r"^Every month · next on 1 Jan 2999"))).to_be_visible()
    page.get_by_label("Every how many").fill("2")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"/recurring$"))
    changed = api.get(f"/recurring/{rule['id']}")
    assert changed["every"] == 2 and changed["postings"] == [] and changed["amount"] == "900.00"


def test_skipping_the_next_occurrence_from_the_edit_page(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    rule = a_rule(api, books)
    page.goto(f"/recurring/{rule['id']}/edit")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Skip 1 Jan 2999").click()
    page.wait_for_url(re.compile(r"/recurring$"))
    expect(page.get_by_text("Nothing was recorded for that one")).to_be_visible()
    assert api.get(f"/recurring/{rule['id']}")["next_date"] == "2999-02-01"


def test_pausing_and_resuming(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    rule = a_rule(api, books)
    page.goto(f"/recurring/{rule['id']}/edit")
    page.get_by_role("button", name="Pause", exact=True).click()
    page.wait_for_url(re.compile(r"/recurring$"))
    paused = section(page, "Paused").get_by_role("link", name=re.compile("^Landlord"))
    expect(paused).to_contain_text("Every month · paused")
    paused.click()
    page.get_by_role("button", name="Resume").click()
    page.wait_for_url(re.compile(r"/recurring$"))
    expect(page.locator("main").get_by_role("link", name=re.compile("^Landlord"))).to_contain_text("next 1 Jan 2999")
    assert api.get(f"/recurring/{rule['id']}")["active"] is True


def test_a_rule_gets_tags_from_the_form_like_a_new_transaction(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    page.goto("/recurring/new")
    page.get_by_label("Amount", exact=True).fill("500")
    pick(page, "Paid from", 0, "Checking")
    pick(page, "Spent on", 0, "Rent")
    page.get_by_label("Starts").fill("2999-01-01")
    page.get_by_role("button", name="Tags", exact=True).click()
    page.get_by_label("Search or create a tag").fill("Home Rent")  # a space becomes a hyphen
    page.get_by_role("button", name="＋ Create “#home-rent”").click()
    page.get_by_role("button", name="Done").click()
    expect(page.get_by_role("button", name="Change the tags")).to_have_text("#home-rent")
    save(page)
    [rule] = api.get("/recurring/")
    assert rule["tags"] == ["home-rent"]
    page.goto(f"/recurring/{rule['id']}/edit")
    expect(page.get_by_role("button", name="Change the tags")).to_have_text("#home-rent")


def test_the_repeat_row_names_its_unit_and_the_end_date_chip_clears(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/recurring/new")
    unit = page.get_by_label("Unit").locator("option:checked")
    expect(unit).to_have_text("month")
    page.get_by_label("Every how many").fill("3")
    expect(unit).to_have_text("months")
    page.get_by_label("Every how many").fill("1")
    expect(unit).to_have_text("month")
    ends = page.get_by_label("Ends (optional)").locator("xpath=..")
    expect(ends).to_contain_text("never")
    expect(page.get_by_role("button", name="No end date")).to_have_count(0)
    page.get_by_label("Ends (optional)").fill("2999-02-01")
    expect(ends).to_contain_text("1 Feb 2999")
    page.get_by_role("button", name="No end date").click()
    expect(ends).to_contain_text("never")
    assert page.get_by_label("Ends (optional)").input_value() == ""


def test_the_recurring_list_is_flat_rows_in_a_tile(signed_in_page: Page, api: Api, books):
    """Rows are as tall as the Transactions rows (not padded twice) and the date has no weekday."""
    page = signed_in_page
    a_rule(api, books)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/recurring")
    row = page.locator("main").get_by_role("link", name=re.compile("^Landlord"))
    expect(row).to_have_count(1)
    box = row.bounding_box()
    assert box and box["height"] < 80, "one title line and one quiet line, no extra padding"
    expect(row).to_contain_text("next 1 Jan 2999")
    api.post(
        "/transactions/",
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
    )
    page.goto("/transactions")
    entry = page.locator("main li").first.bounding_box()
    assert entry and abs(entry["height"] - box["height"]) <= 2, "as tall as a Transactions row"


def test_the_past_start_hint_shows_only_for_a_past_start(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/recurring/new")
    hint = page.get_by_text("A start date in the past is recorded right away for every missed date.")
    expect(hint).to_have_count(0)
    page.get_by_label("Starts").fill("2020-01-15")
    expect(hint).to_be_visible()
    page.get_by_label("Starts").fill("2999-01-15")
    expect(hint).to_have_count(0)


def test_a_rules_row_settings_take_no_date(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/recurring/new")
    page.get_by_label("Amount", exact=True).fill("100")
    pick(page, "Paid from", 0, "Checking")
    section(page, "Paid from").get_by_role("button", name="Amount and date").click()
    sheet = page.locator("dialog[open]")
    expect(sheet.get_by_label("Amount", exact=True)).to_be_visible()
    expect(sheet.get_by_label("Date")).to_have_count(0)


def test_the_bells_open_rule_reaches_the_form(signed_in_page: Page, api: Api, books, session):
    from sqlmodel import select

    from app.models.recurring import RecurringTransaction

    page = signed_in_page
    rule = a_rule(api, books)
    found = session.exec(select(RecurringTransaction)).one()
    found.last_error = "Checking can no longer be posted to"
    session.add(found)
    session.commit()
    page.goto("/")
    page.get_by_role("banner").get_by_role("button", name="To do").click()
    page.get_by_role("dialog", name="To do").get_by_role("link", name="Open rule").click()
    page.wait_for_url(f"**/recurring/{rule['id']}/edit")
    expect(page.get_by_role("alert")).to_contain_text("Couldn't record Checking can no longer be posted to.")


def test_deleting_a_rule_goes_back_to_the_list(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    rule = a_rule(api, books)
    page.goto(f"/recurring/{rule['id']}/edit")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete", exact=True).click()
    page.wait_for_url(re.compile(r"/recurring$"))
    expect(page.get_by_text("Recurring transaction deleted. What it recorded is kept.")).to_be_visible()
    expect(page.get_by_text("Nothing on repeat yet")).to_be_visible()
    assert api.get("/recurring/") == []
