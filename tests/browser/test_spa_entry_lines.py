"""The React app's Add screen with several lines on a side, each with its own amount and posting day (ports of
test_transaction_form.py, test_posting_date.py and test_category_chip.py)."""

import re
from datetime import timedelta

from playwright.sync_api import Page, expect

from app.clock import local_today

from ..books import leg
from .conftest import Api
from .test_spa_entry import choose


def section(page: Page, title: str):
    return page.locator("section", has=page.get_by_role("heading", name=title, exact=True))


def rows(page: Page, title: str):
    return section(page, title).get_by_role("button", name=re.compile(f"^{title}"))


def pick(page: Page, title: str, index: int, label: str):
    rows(page, title).nth(index).click()
    page.get_by_role("dialog", name=title).get_by_role("button", name=re.compile(re.escape(label))).first.click()


def tune(page: Page, title: str, index: int = 0, amount: str | None = None, day: str | None = None):
    section(page, title).get_by_role("button", name="Amount and date").nth(index).click()
    sheet = page.locator("dialog[open]")
    if amount is not None:
        sheet.get_by_label("Amount", exact=True).fill(amount)
    if day is not None:
        sheet.get_by_label("Date").fill(day)
    sheet.get_by_role("button", name="Done").click()
    expect(sheet).to_have_count(0)


def card(api: Api, books, name="Regalia Gold"):
    return api.post("/accounts/", name=name, parent_id=books["roots"]["Liabilities"], statement_day=16, due_day=5)


def test_typing_less_adds_a_row_with_the_remainder_and_removing_it_brings_it_back(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("1000")
    choose(page, "Paid from", "Checking")
    choose(page, "Spent on", "Groceries")
    tune(page, "Spent on", amount="600")
    expect(rows(page, "Spent on")).to_have_count(2)
    expect(rows(page, "Spent on").nth(0)).to_contain_text("600.00")
    expect(rows(page, "Spent on").nth(1)).to_contain_text("400.00 left")
    tune(page, "Spent on", amount="1000")
    expect(rows(page, "Spent on")).to_have_count(1)


def test_a_row_is_removed_from_its_own_sheet_and_one_category_is_the_whole_amount_again(
    signed_in_spa_page: Page, spa_books
):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("1000")
    choose(page, "Paid from", "Checking")
    choose(page, "Spent on", "Groceries")
    tune(page, "Spent on", amount="600")
    pick(page, "Spent on", 1, "Rent")
    section(page, "Spent on").get_by_role("button", name="Amount and date").nth(0).click()
    page.locator("dialog[open]").get_by_role("button", name="Remove").click()
    expect(rows(page, "Spent on")).to_have_count(1)
    expect(rows(page, "Spent on").first).to_have_text(re.compile(r"Rent$"))


def test_the_settings_sheet_has_two_cells_a_done_pill_and_a_red_remove_below_it(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("1250")
    choose(page, "Paid from", "Checking")
    section(page, "Paid from").get_by_role("button", name="Amount and date").click()
    sheet = page.locator("dialog[open]")
    expect(sheet.get_by_label("Amount", exact=True)).to_have_value("1,250.00")
    assert sheet.get_by_label("Date").get_attribute("type") == "date", "the device's own date picker"
    expect(sheet.get_by_label("Date")).to_have_value(str(local_today()))
    amount_box, date_box = (
        sheet.get_by_label("Amount", exact=True).bounding_box(),
        sheet.get_by_label("Date").bounding_box(),
    )
    assert amount_box and date_box and abs(amount_box["y"] - date_box["y"]) < 4, "two cells side by side"
    expect(sheet.get_by_role("button", name="Remove")).to_have_count(0)
    sheet.get_by_label("Amount", exact=True).fill("1000")
    sheet.get_by_role("button", name="Done").click()
    section(page, "Paid from").get_by_role("button", name="Amount and date").first.click()
    remove, done = sheet.get_by_role("button", name="Remove"), sheet.get_by_role("button", name="Done")
    expect(remove).to_be_in_viewport()  # the sheet has finished rising
    done_box, remove_box = done.bounding_box(), remove.bounding_box()
    assert done_box and remove_box and remove_box["y"] > done_box["y"], "Remove sits below Done"
    assert done.evaluate("el => getComputedStyle(el).borderRadius") == "999px", "a pill"
    red = page.evaluate(
        """() => { const probe = document.createElement('span'); probe.style.color = 'var(--negative)';
        document.body.append(probe); const c = getComputedStyle(probe).color; probe.remove(); return c; }"""
    )
    assert remove.evaluate("el => getComputedStyle(el).color") == red, "red, from the token"


def test_a_row_shows_its_amount_only_when_it_differs_from_the_total(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("500")
    choose(page, "Paid from", "Checking")
    expect(rows(page, "Paid from").first).not_to_contain_text("500")
    tune(page, "Paid from", amount="200")
    expect(rows(page, "Paid from").first).to_contain_text("200.00")


def test_a_later_date_is_stored_and_shown_on_the_row(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    regalia = card(spa_api, spa_books)
    later = str(local_today() + timedelta(days=2))
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("180")
    choose(page, "Paid from", "Regalia Gold")
    tune(page, "Paid from", day=later)
    expect(rows(page, "Paid from").first).to_contain_text("Posts")
    expect(rows(page, "Paid from").first).not_to_contain_text("180")
    choose(page, "Spent on", "Groceries")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    [entry] = spa_api.get("/transactions/")[:1]
    line = next(p for p in entry["postings"] if p["account_id"] == regalia["id"])
    assert line["posted_on"] == later
    assert all(p["posted_on"] is None for p in entry["postings"] if p["account_id"] != regalia["id"])


def test_a_split_across_two_cards_has_a_date_for_each(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    regalia, neu = card(spa_api, spa_books), card(spa_api, spa_books, "NEUCARD")
    later = str(local_today() + timedelta(days=3))
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("1250")
    choose(page, "Paid from", "Regalia Gold")
    tune(page, "Paid from", amount="800", day=later)
    expect(rows(page, "Paid from").nth(1)).to_contain_text("450.00 left")
    pick(page, "Paid from", 1, "NEUCARD")
    expect(rows(page, "Paid from").nth(1)).to_contain_text("450.00")
    choose(page, "Spent on", "Groceries")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    [entry] = spa_api.get("/transactions/")[:1]
    days = {p["account_id"]: p["posted_on"] for p in entry["postings"] if p["side"] == "credit"}
    assert days == {regalia["id"]: later, neu["id"]: None}


def test_editing_shows_a_posting_date_and_keeps_it(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    regalia = card(spa_api, spa_books)
    on, later = str(local_today() - timedelta(days=5)), str(local_today() - timedelta(days=2))
    entry = spa_api.post(
        "/transactions/",
        date=on,
        payee="IGST",
        postings=[leg(spa_books["food"], "debit", "180"), {**leg(regalia, "credit", "180"), "posted_on": later}],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(rows(page, "Paid from").first).to_contain_text("Posts")
    page.get_by_placeholder("Payee or Merchant?").fill("IGST on fuel")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    kept = spa_api.get(f"/transactions/{entry['id']}")
    assert next(p for p in kept["postings"] if p["account_id"] == regalia["id"])["posted_on"] == later


def test_an_entry_with_several_lines_opens_with_them(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    entry = spa_api.post(
        "/transactions/",
        payee="DMart",
        postings=[
            leg(spa_books["food"], "debit", "600"),
            leg(spa_books["rent"], "debit", "400"),
            leg(spa_books["checking"], "credit", "1000"),
        ],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(rows(page, "Spent on")).to_have_count(2)
    expect(rows(page, "Spent on").nth(0)).to_contain_text("600.00")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    amounts = sorted(p["amount"] for p in spa_api.get(f"/transactions/{entry['id']}")["postings"])
    assert amounts == ["1000.00", "400.00", "600.00"]


def test_moving_the_entry_past_a_posting_date_puts_the_line_back_on_the_entrys_day(
    signed_in_spa_page: Page, spa_books, spa_api: Api
):
    page = signed_in_spa_page
    card(spa_api, spa_books)
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("180")
    choose(page, "Paid from", "Regalia Gold")
    tune(page, "Paid from", day=str(local_today() + timedelta(days=1)))
    expect(rows(page, "Paid from").first).to_contain_text("Posts")
    page.get_by_label("Date", exact=True).first.fill(str(local_today() + timedelta(days=4)))
    expect(rows(page, "Paid from").first).not_to_contain_text("Posts")
