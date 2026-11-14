"""The React app's Add screen sharing a bill or an income with people (ports of test_people.py's Split tests)."""

import re

from playwright.sync_api import Page, expect

from .conftest import Api
from .test_spa_entry import choose
from .test_spa_entry_lines import tune


def person(api: Api, name: str = "Alice") -> dict:
    return api.post("/contacts/", name=name)


def split(page: Page):
    page.get_by_role("radio", name="Split").check()


def add_people(page: Page, *names: str):
    page.get_by_role("button", name="+ Add people").click()
    sheet = page.get_by_role("dialog", name="Split with")
    for name in names:
        sheet.get_by_role("button", name=name, exact=True).click()
    sheet.get_by_role("button", name=re.compile("^Done")).click()
    expect(sheet).to_have_count(0)


def field(page: Page, label: str, option: str):
    page.get_by_role("button", name=re.compile(f"^{label}:")).click()
    page.get_by_role("dialog", name=label).get_by_role("button", name=re.compile(re.escape(option))).first.click()


def preview(page: Page):
    return page.locator("[aria-live=polite]").filter(has_text=re.compile("After this|owes|choose"))


def test_more_rows_is_still_simple_split_is_for_people(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    person(spa_api)
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("1000")
    choose(page, "Paid from", "Checking")
    choose(page, "Spent on", "Groceries")
    tune(page, "Spent on", amount="600")
    expect(page.get_by_role("radio", name="Simple")).to_be_checked()
    split(page)
    page.get_by_role("radio", name="Simple").check()
    expect(page.get_by_role("button", name=re.compile("^Spent on"))).to_have_count(2)


def test_a_bill_shared_shows_its_result_as_you_type(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    alice, bob = person(spa_api), person(spa_api, "Bob")
    page.goto(f"/transactions/new?mode=split&with={alice['id']}")
    expect(page.get_by_role("button", name="Remove Alice")).to_be_visible()
    page.get_by_label("Amount", exact=True).fill("900")
    page.get_by_placeholder("Payee or Merchant?").fill("Dinner")
    field(page, "Category", "Groceries")
    field(page, "You paid from", "Checking")
    expect(preview(page)).to_contain_text("Alice owes you")
    expect(preview(page)).to_contain_text("450.00")
    add_people(page, "Bob")
    expect(preview(page)).to_contain_text("Bob owes you")
    expect(preview(page)).to_contain_text("300.00")
    page.get_by_role("radio", name="%").check()
    page.get_by_label("Your share value").fill("50")
    page.get_by_label("Alice's share value").fill("30")
    page.get_by_label("Bob's share value").fill("20")
    expect(preview(page)).to_contain_text("270.00")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert float(spa_api.get(f"/contacts/{alice['id']}")["receivable"]) == 270
    assert float(spa_api.get(f"/contacts/{bob['id']}")["receivable"]) == 180


def test_switching_to_split_carries_over_what_the_rows_say(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    alice = person(spa_api)
    person(spa_api, "Bob")
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("1500")
    page.get_by_placeholder("Payee or Merchant?").fill("Dinner")
    choose(page, "Paid from", "Checking")
    choose(page, "Spent on", "Groceries")
    split(page)
    expect(page.get_by_role("button", name=re.compile("^Category:"))).to_have_text("Groceries")
    expect(page.get_by_role("button", name=re.compile("^You paid from:"))).to_have_text("Checking")
    add_people(page, "Alice", "Bob")
    expect(preview(page)).to_contain_text("500.00")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert float(spa_api.get(f"/contacts/{alice['id']}")["receivable"]) == 500
    assert float(next(a for a in spa_api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 3500


def test_a_friend_who_paid_can_be_recorded(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    alice = person(spa_api)
    page.goto(f"/transactions/new?mode=split&with={alice['id']}")
    page.get_by_label("Amount", exact=True).fill("1000")
    field(page, "Category", "Groceries")
    page.get_by_text("Someone else paid some of it").click()
    page.get_by_role("textbox", name=re.compile("^You paid")).fill("0")
    page.get_by_label("Alice paid").fill("1000")
    expect(preview(page)).to_contain_text("Alice")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    got = spa_api.get(f"/contacts/{alice['id']}")
    assert float(got["payable"]) == 500 and float(got["receivable"]) == 0


def test_the_share_rows_sit_in_a_line(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    alice = person(spa_api)
    page.goto(f"/transactions/new?mode=split&with={alice['id']}")
    you, her = page.get_by_text("You", exact=True), page.get_by_text("Alice", exact=True)
    you_box, her_box = you.bounding_box(), her.bounding_box()
    assert you_box and her_box and abs(you_box["x"] - her_box["x"]) < 2, "the names line up"
    remove = page.get_by_role("button", name="Remove Alice").bounding_box()
    assert remove and abs((remove["y"] + remove["height"] / 2) - (her_box["y"] + her_box["height"] / 2)) < 6
    page.get_by_role("radio", name="%").check()
    expect(page.get_by_label("Alice's share value")).to_be_visible()


def test_an_old_expense_can_be_edited_into_a_shared_bill(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    alice = person(spa_api)
    person(spa_api, "Bob")
    entry = spa_api.post(
        "/transactions/",
        payee="Restaurant",
        date="2026-10-09",
        postings=[
            {"category_id": spa_books["food"]["id"], "side": "debit", "amount": "3000"},
            {"account_id": spa_books["checking"]["id"], "side": "credit", "amount": "3000"},
        ],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.get_by_role("radio", name="Simple")).to_be_checked()
    split(page)
    expect(page.get_by_role("button", name=re.compile("^Category:"))).to_have_text("Groceries")
    add_people(page, "Alice", "Bob")
    expect(preview(page)).to_contain_text("1,000.00")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(lambda u: "/edit" not in u)
    assert float(spa_api.get(f"/contacts/{alice['id']}")["receivable"]) == 1000
    assert spa_api.get(f"/transactions/{entry['id']}")["date"] == "2026-10-09"
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.get_by_role("radio", name="Split")).to_be_checked()
    expect(page.get_by_role("button", name="Remove Bob")).to_be_visible()


def test_income_shared_with_a_person(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    who = person(spa_api)
    page.goto("/transactions/new")
    page.get_by_role("button", name="Income", exact=True).click()
    page.get_by_label("Amount", exact=True).fill("10000")
    page.get_by_placeholder("Payee or Merchant?").fill("Rent, Flat 4B")
    split(page)
    field(page, "Earned from", "Salary")
    field(page, "Paid into", "Checking")
    add_people(page, "Alice")
    page.get_by_label("Alice's part").fill("4000")
    expect(preview(page)).to_contain_text("Your income")
    expect(preview(page)).to_contain_text("6,000.00")
    expect(preview(page)).to_contain_text("you hold it for them")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert float(spa_api.get(f"/contacts/{who['id']}")["payable"]) == 4000
    assert float(next(a for a in spa_api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 15000
    entry = next(t for t in spa_api.get("/transactions/") if t["payee"] == "Rent, Flat 4B")
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.get_by_role("radio", name="Split")).to_be_checked()
    expect(page.get_by_label("Alice's part")).to_have_value("4,000.00")


def test_only_the_people_added_are_listed_and_the_sheet_adds_and_removes_them(
    signed_in_spa_page: Page, spa_books, spa_api: Api
):
    page = signed_in_spa_page
    person(spa_api)
    person(spa_api, "Bob")
    person(spa_api, "Carol")
    page.goto("/transactions/new")
    split(page)
    expect(page.get_by_role("button", name=re.compile("^Remove"))).to_have_count(0)  # only you
    page.get_by_role("button", name="+ Add people").click()
    sheet = page.get_by_role("dialog", name="Split with")
    expect(sheet.get_by_role("button", name=re.compile("^(Alice|Bob|Carol)$"))).to_have_count(3)
    sheet.get_by_label("Search people").fill("bo")
    expect(sheet.get_by_role("button", name=re.compile("^(Alice|Bob|Carol)$"))).to_have_count(1)
    sheet.get_by_label("Search people").fill("")
    sheet.get_by_role("button", name="Alice", exact=True).click()
    sheet.get_by_role("button", name="Bob", exact=True).click()
    expect(sheet.get_by_role("button", name=re.compile("^Done"))).to_have_text("Done · 2 people")
    sheet.get_by_role("button", name=re.compile("^Done")).click()
    expect(page.get_by_role("button", name=re.compile("^Remove"))).to_have_count(2)
    page.get_by_role("button", name="Remove Bob").click()
    expect(page.get_by_role("button", name=re.compile("^Remove"))).to_have_count(1)
    page.get_by_text("Someone else paid some of it").click()
    expect(page.get_by_label(re.compile(r"^\w+ paid$"))).to_have_count(1)  # only Alice: the one who is in the bill


def test_the_mode_switch_looks_like_the_kind_switch(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    person(spa_api)
    page.goto("/transactions/new")
    look = """(el) => { const s = getComputedStyle(el);
        return {radius: s.borderRadius, colour: s.color, weight: s.fontWeight, shadow: s.boxShadow}; }"""
    kind = page.get_by_role("button", name="Expense", exact=True).evaluate(look)
    mode = page.get_by_role("radio", name="Simple").locator("xpath=..").evaluate(look)
    assert kind == mode
