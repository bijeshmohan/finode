"""The posting date on the Add screen: a chosen row's glyph opens its amount and date in a small sheet; Done sets them."""

import re
from datetime import timedelta

from playwright.sync_api import Page, expect

from app.clock import local_today

from ..books import leg
from .conftest import Api, add_row, row_button, row_gear, set_row


def card(api: Api, books, name="Regalia Gold", **extra):
    return api.post(
        "/accounts/", name=name, parent_id=books["roots"]["Liabilities"], statement_day=16, due_day=5, **extra
    )


def test_the_sheet_asks_for_the_amount_and_a_native_date_both_filled_in(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.fill("#total", "1250")
    row_button(page, "credit").click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").click()
    row_gear(page, "credit").click()
    sheet = page.locator("#row-settings")
    amount, day = sheet.locator("[data-config-amount]"), sheet.locator("[data-config-date]")
    assert amount.input_value() == "1,250.00", "the whole total, to begin with"
    assert day.get_attribute("type") == "date", "the device's own date picker"
    assert day.input_value() == page.input_value('input[name="date"]'), "the entry's own date, to begin with"
    expect(sheet.locator(".pick-field", has_text="Date")).to_have_text("Date")
    assert "of 1,250" not in sheet.inner_text() and "Posting" not in sheet.inner_text(), "nothing else is said"


def test_a_later_date_is_stored_shown_on_the_row_and_changes_the_bill(page: Page, books, api: Api):
    regalia = card(api, books)
    today = local_today()
    later = str(today + timedelta(days=2))
    page.goto("/transactions/new")
    page.fill("#total", "180")
    add_row(page, "credit", "Regalia Gold", date=later)
    expect(row_button(page, "credit")).to_contain_text("Posts")
    expect(row_button(page, "credit")).not_to_contain_text("180")  # the whole total: no amount on the row
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = api.get("/transactions/")[:1]
    line = next(p for p in entry["postings"] if p["account_id"] == regalia["id"])
    assert line["posted_on"] == later
    assert all(p["posted_on"] is None for p in entry["postings"] if p["account_id"] != regalia["id"])


def test_the_entrys_own_date_stores_nothing_and_shows_nothing(page: Page, books, api: Api):
    card(api, books)
    page.goto("/transactions/new")
    page.fill("#total", "180")
    add_row(page, "credit", "Regalia Gold")
    expect(row_button(page, "credit")).to_have_text("Regalia Gold")
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = api.get("/transactions/")[:1]
    assert all(p["posted_on"] is None for p in entry["postings"])


def test_a_split_across_two_cards_has_a_date_for_each(page: Page, books, api: Api):
    regalia = card(api, books)
    neu = card(api, books, "NEUCARD")
    later = str(local_today() + timedelta(days=3))
    page.goto("/transactions/new")
    page.fill("#total", "1250")
    add_row(page, "credit", "Regalia Gold", amount="800", date=later)
    expect(row_button(page, "credit", 0)).to_contain_text("800.00")
    expect(row_button(page, "credit", 1)).to_contain_text("450.00 left")  # the next row appears with what is left
    add_row(page, "credit", "NEUCARD", index=1)
    expect(row_button(page, "credit", 1)).to_contain_text("450.00")
    expect(page.locator('[data-rows="credit"] [data-row]')).to_have_count(2)
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = api.get("/transactions/")[:1]
    days = {p["account_id"]: p["posted_on"] for p in entry["postings"] if p["side"] == "credit"}
    assert days == {regalia["id"]: later, neu["id"]: None}


def test_editing_shows_a_posting_date_and_keeps_it(page: Page, books, api: Api):
    regalia = card(api, books)
    on = str(local_today() - timedelta(days=5))
    later = str(local_today() - timedelta(days=2))
    entry = api.post(
        "/transactions/",
        date=on,
        payee="IGST",
        postings=[leg(books["food"], "debit", "180"), {**leg(regalia, "credit", "180"), "posted_on": later}],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(row_button(page, "credit")).to_contain_text("Posts")
    page.fill('input[name="payee"]', "IGST on fuel")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url("**/transactions")
    kept = api.get(f"/transactions/{entry['id']}")
    assert next(p for p in kept["postings"] if p["account_id"] == regalia["id"])["posted_on"] == later


def test_moving_the_entry_past_a_posting_date_puts_the_line_back_on_the_entrys_day(page: Page, books, api: Api):
    card(api, books)
    page.goto("/transactions/new")
    page.fill("#total", "180")
    add_row(page, "credit", "Regalia Gold", date=str(local_today() + timedelta(days=1)))
    expect(row_button(page, "credit")).to_contain_text("Posts")
    page.fill('input[name="date"]', str(local_today() + timedelta(days=4)))
    expect(row_button(page, "credit")).not_to_contain_text("Posts")
    assert page.input_value('[data-rows="credit"] [name="posted_on"]') == ""


def test_every_account_takes_a_date_but_a_category_and_a_recurring_rule_do_not(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.fill("#total", "50")
    row_button(page, "credit").click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").click()
    row_gear(page, "credit").click()
    expect(page.locator("#row-settings [data-config-date-field]")).to_be_visible()
    page.keyboard.press("Escape")
    row_button(page, "debit").click()
    page.locator("#row-picker [data-pick-option]", has_text="Groceries").click()
    row_gear(page, "debit").click()
    expect(page.locator("#row-settings [data-config-date-field]")).to_be_hidden()
    page.keyboard.press("Escape")
    page.goto("/recurring/new")
    row_button(page, "credit").click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").click()
    row_gear(page, "credit").click()
    expect(page.locator("#row-settings [data-config-date-field]")).to_be_hidden()


def test_a_row_is_removed_from_its_own_sheet(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    page.select_option('[data-rows="credit"] select', label="Checking")
    set_row(page, "credit", 0, amount="60")
    page.select_option('[data-rows="credit"] [data-row]:nth-child(2) select', label="Cash")
    row_gear(page, "credit", 1).click()
    page.locator("#row-settings [data-config-remove]").click()
    expect(page.locator('[data-rows="credit"] [data-row]')).to_have_count(2)  # the open row for what is left is back
    assert page.input_value('[data-rows="credit"] [data-row]:nth-child(2) select') == ""


def test_the_picker_only_picks_and_the_row_has_a_glyph_for_its_settings(page: Page, books):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    expect(row_gear(page, "credit")).to_be_hidden()  # nothing chosen yet, nothing to set
    row_button(page, "credit").click()
    picker = page.locator("#row-picker")
    picker.locator("[data-pick-option]", has_text="Checking").click()
    expect(picker).to_be_hidden()  # one tap chooses
    assert page.locator("#row-picker [data-config-amount], #row-picker [data-config-date]").count() == 0
    expect(row_gear(page, "credit")).to_be_visible()
    expect(row_gear(page, "credit")).not_to_have_class(re.compile(r"\bset\b"))
    set_row(page, "credit", amount="60", date=str(local_today() + timedelta(days=2)))
    expect(row_button(page, "credit")).to_contain_text("60.00")
    expect(row_button(page, "credit")).to_contain_text("Posts")
    expect(row_gear(page, "credit")).to_have_class(re.compile(r"\bset\b"))  # the glyph shows the row differs
    row_gear(page, "credit").click()  # and its settings open as they were left
    assert page.input_value("#row-settings [data-config-amount]") == "60.00"
    assert page.input_value("#row-settings [data-config-date]") == str(local_today() + timedelta(days=2))


def test_the_settings_sheet_has_two_cells_a_done_pill_and_a_red_remove_below_it(page: Page, books):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    add_row(page, "credit", "Checking")
    row_gear(page, "credit").click()
    sheet = page.locator("#row-settings")
    amount, day = sheet.locator(".pick-field", has_text="Amount"), sheet.locator(".pick-field", has_text="Date")
    a, d = amount.bounding_box(), day.bounding_box()
    assert abs(a["y"] - d["y"]) < 2 and a["x"] < d["x"], "amount and date side by side"
    done, remove = sheet.locator("[data-config-ok]"), sheet.locator("[data-config-remove]")
    assert done.inner_text().strip() == "Done" and sheet.locator("[data-config-ok] svg").count() == 0, "a word, no tick"
    assert a["y"] + a["height"] <= done.bounding_box()["y"] <= remove.bounding_box()["y"], "fields, Done, then Remove"
    red = page.evaluate(
        "() => { const i = document.createElement('i'); i.style.color = 'var(--negative)'; document.body.append(i); return getComputedStyle(i).color; }"
    )
    assert remove.evaluate("el => getComputedStyle(el).color") == red, "Remove is red"
    done.click()
    expect(sheet).to_be_hidden()
