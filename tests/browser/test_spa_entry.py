"""The React app's Add and Edit screen in a browser (ports of test_transaction_form.py, test_account_picker.py,
test_row_category.py and test_tags.py for what the Simple form does)."""

import re

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def side(page: Page, title: str):
    return page.get_by_role("button", name=re.compile(f"^{title}"))


def choose(page: Page, title: str, label: str):
    side(page, title).click()
    page.get_by_role("dialog", name=title).get_by_role("button", name=re.compile(re.escape(label))).first.click()


def offered(page: Page, title: str) -> list[str]:
    side(page, title).click()
    sheet = page.get_by_role("dialog", name=title)
    found = sheet.get_by_role("heading", level=3).all_inner_texts()
    page.keyboard.press("Escape")
    expect(sheet).to_be_hidden()
    return found


def test_the_kind_buttons_narrow_the_pickers(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    assert (offered(page, "Paid from"), offered(page, "Spent on")) == (["Assets", "Liabilities"], ["Expenses"])
    page.get_by_role("button", name="Income", exact=True).click()
    assert (offered(page, "Earned from"), offered(page, "Paid into")) == (["Income"], ["Assets", "Liabilities"])
    page.get_by_role("button", name="Transfer", exact=True).click()
    assert offered(page, "From") == ["Assets", "Liabilities"]
    page.get_by_role("button", name="Transfer", exact=True).click()  # tapping the selected kind again selects nothing
    expect(page.locator("[aria-pressed=true]", has_text="Transfer")).to_have_count(0)
    assert len(offered(page, "From")) == 5, "no kind offers every account"


def test_the_order_and_the_default(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    kinds = page.get_by_role("group", name=re.compile("What kind of entry")).get_by_role("button")
    expect(kinds).to_have_count(3)
    assert kinds.all_inner_texts() == ["Expense", "Income", "Transfer"]
    expect(page.get_by_role("button", name="Expense", exact=True)).to_have_attribute("aria-pressed", "true")


def test_a_choice_survives_a_kind_that_still_offers_it(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    choose(page, "Paid from", "Checking")
    page.get_by_role("button", name="Transfer", exact=True).click()
    expect(side(page, "From")).to_contain_text("Checking")
    page.get_by_role("button", name="Income", exact=True).click()
    expect(side(page, "Earned from")).not_to_contain_text("Checking"), "an asset is not an income source"


def test_saving_an_expense(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    page.get_by_label("Amount").fill("250")
    choose(page, "Paid from", "Checking")
    choose(page, "Spent on", "Groceries")
    page.get_by_placeholder("Payee or Merchant?").fill("DMart")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    expect(page.get_by_role("button", name=re.compile("^DMart"))).to_be_visible()
    [entry] = [t for t in spa_api.get("/transactions/") if t["payee"] == "DMart"]
    assert {(p["side"], p["amount"]) for p in entry["postings"]} == {("debit", "250.00"), ("credit", "250.00")}


def test_swapping_from_and_to_keeps_a_transfer_and_an_expense_has_no_swap(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    expect(page.get_by_role("button", name="Swap From and To")).to_have_count(0)
    page.get_by_role("button", name="Transfer", exact=True).click()
    choose(page, "From", "Checking")
    choose(page, "To", "Cash")
    page.get_by_role("button", name="Swap From and To").click()
    expect(side(page, "From")).to_contain_text("Cash")
    expect(side(page, "To")).to_contain_text("Checking")
    expect(page.get_by_role("button", name="Transfer", exact=True)).to_have_attribute("aria-pressed", "true")


def test_editing_keeps_what_was_recorded(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    entry = spa_api.post(
        "/transactions/",
        payee="Old",
        postings=[leg(spa_books["food"], "debit", "40"), leg(spa_books["checking"], "credit", "40")],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.get_by_role("button", name="Expense", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_label("Amount")).to_have_value("40.00")
    page.get_by_label("Amount").fill("55")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert {p["amount"] for p in spa_api.get(f"/transactions/{entry['id']}")["postings"]} == {"55.00"}


def test_deleting_from_the_edit_screen_goes_back_to_the_list(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    entry = spa_api.post(
        "/transactions/",
        payee="Gone",
        postings=[leg(spa_books["food"], "debit", "40"), leg(spa_books["checking"], "credit", "40")],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete transaction").click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    expect(page.get_by_text("Transaction deleted")).to_be_visible()
    expect(page.get_by_text("transaction not found")).to_have_count(0)


def history(api: Api, books, payee="Swiggy", source="card", target="food"):
    api.post(
        "/transactions/",
        payee=payee,
        postings=[leg(books[target], "debit", "100"), leg(books[source], "credit", "100")],
    )


def chips(page: Page):
    return page.get_by_role("group", name="People you pay").get_by_role("button")


def test_a_payee_chip_fills_the_payee_only_and_moves_on_to_the_amount(
    signed_in_spa_page: Page, spa_books, spa_api: Api
):
    page = signed_in_spa_page
    history(spa_api, spa_books)
    page.goto("/transactions/new")
    expect(chips(page)).to_have_count(0)
    page.get_by_placeholder("Payee or Merchant?").fill("sw")
    chips(page).filter(has_text="Swiggy").click()
    expect(page.get_by_placeholder("Payee or Merchant?")).to_have_value("Swiggy")
    expect(chips(page)).to_have_count(0)
    expect(side(page, "Paid from")).to_contain_text("Account…")
    expect(page.get_by_label("Amount")).to_be_focused()


def test_the_chips_narrow_as_you_type(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    history(spa_api, spa_books, "Swiggy")
    history(spa_api, spa_books, "DMart", "checking")
    page.goto("/transactions/new")
    page.get_by_placeholder("Payee or Merchant?").fill("dm")
    expect(chips(page)).to_have_count(1)
    expect(chips(page)).to_have_text("DMart")
    page.get_by_placeholder("Payee or Merchant?").fill("")
    expect(chips(page)).to_have_count(0)


def test_the_amount_is_focused_on_a_computer_but_not_on_a_phone(
    signed_in_spa_page: Page, spa_books, browser, spa_server
):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    expect(page.get_by_label("Amount")).to_be_focused()  # the test page has a mouse
    phone = browser.new_context(
        viewport={"width": 390, "height": 844}, base_url=spa_server, has_touch=True, is_mobile=True
    )
    try:
        phone.add_cookies(page.context.cookies())
        mobile = phone.new_page()
        mobile.goto("/transactions/new")
        expect(mobile.get_by_label("Amount")).to_be_visible()
        expect(mobile.get_by_label("Amount")).not_to_be_focused()
    finally:
        phone.close()


def test_an_amount_cannot_be_typed_with_two_decimal_points_or_letters(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    amount = page.get_by_label("Amount")
    amount.press_sequentially("12a.3.45")
    expect(amount).to_have_value("12.34")


def test_the_amount_is_grouped_as_it_is_typed_and_the_cursor_stays(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    amount = page.get_by_label("Amount")
    amount.press_sequentially("1234567")
    expect(amount).to_have_value(re.compile(r"^(12,34,567|1,234,567)$"))
    assert amount.evaluate("e => e.selectionStart") == len(amount.input_value())


def test_add_related_opens_the_form_linked_and_saves_the_link(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    first = spa_api.post(
        "/transactions/",
        payee="Amazon",
        postings=[leg(spa_books["food"], "debit", "4998"), leg(spa_books["card"], "credit", "4998")],
    )
    page.goto(f"/transactions/new?related={first['id']}")
    expect(page.get_by_text("Related to")).to_be_visible()
    page.get_by_label("Amount").fill("1000")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.get_by_role("button", name="Transfer", exact=True).click()  # every account
    choose(page, "From", "Groceries")
    choose(page, "To", "Visa")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert any(t.get("related_id") == first["id"] for t in spa_api.get("/transactions/"))


def test_the_picker_relates_an_entry_and_the_chip_removes_it(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    history(spa_api, spa_books, "Amazon")
    page.goto("/transactions/new")
    page.get_by_role("button", name="Related").click()
    page.get_by_label("Search transactions").fill("ama")
    page.get_by_role("dialog", name="Related to…").get_by_role("button", name=re.compile("Amazon")).click()
    expect(page.get_by_text("Related to")).to_be_visible()
    page.get_by_role("button", name="Remove the link").click()
    expect(page.get_by_role("button", name="Related")).to_be_visible()


def test_the_date_is_a_chip_that_names_the_day(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    expect(page.get_by_label("Date").locator("xpath=..")).to_contain_text(re.compile(r"^Today, \d{1,2} \w{3}"))


def test_an_account_is_chosen_in_a_sheet_and_the_other_side_is_greyed(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    page.get_by_role("button", name="Transfer", exact=True).click()
    choose(page, "From", "Checking")
    side(page, "To").click()
    sheet = page.get_by_role("dialog", name="To")
    expect(sheet.get_by_role("button", name=re.compile("Checking"))).to_be_disabled()
    expect(sheet.get_by_role("button", name=re.compile("Cash"))).to_be_enabled()


def test_the_chosen_account_is_bold(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    choose(page, "Paid from", "Checking")
    side(page, "Paid from").click()
    chosen = page.get_by_role("dialog", name="Paid from").get_by_role("button", name=re.compile("Checking"))
    expect(chosen).to_have_attribute("aria-pressed", "true")
    assert int(chosen.evaluate("e => getComputedStyle(e).fontWeight")) >= 600


def test_pressing_an_option_keeps_the_search_focused_so_the_sheet_does_not_move(signed_in_spa_page: Page, spa_books):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    side(page, "Paid from").click()
    search = page.get_by_role("dialog", name="Paid from").get_by_label("Search")
    search.click()
    option = page.get_by_role("dialog", name="Paid from").get_by_role("button", name=re.compile("Checking"))
    box = option.bounding_box()
    assert box
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    page.mouse.down()
    expect(search).to_be_focused()
    page.mouse.up()


def test_the_category_line_shows_only_when_money_leaves_the_budget(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    loan = spa_api.post("/accounts/", name="Home Loan", parent_id=spa_books["roots"]["Liabilities"], on_budget=False)
    assert loan
    page.goto("/transactions/new")
    page.get_by_role("button", name="Transfer", exact=True).click()
    choose(page, "From", "Checking")
    expect(page.get_by_role("button", name=re.compile("^Category"))).to_have_count(0)
    choose(page, "To", "Home Loan")
    category = page.get_by_role("button", name=re.compile("^Category"))
    expect(category).to_contain_text("No category")  # nothing is filled in
    category.click()
    page.get_by_role("dialog", name="Category").get_by_role("button", name=re.compile("Rent")).click()
    expect(category).to_contain_text("Rent")


def test_choosing_tags_and_making_a_new_one(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    page.goto("/transactions/new")
    page.get_by_label("Amount").fill("12")
    choose(page, "Paid from", "Checking")
    choose(page, "Spent on", "Groceries")
    page.get_by_label("Note").fill("lunch #work")
    page.get_by_role("button", name="Tags", exact=True).click()
    page.get_by_label("Search or create a tag").fill("Goa Trip")
    page.get_by_role("button", name="＋ Create “#goa-trip”").click()
    page.get_by_role("button", name="Done").click()
    expect(page.get_by_role("button", name="Change the tags")).to_have_text("#goa-trip")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    newest = spa_api.get("/transactions/")[0]
    assert newest["tags"] == ["goa-trip"] and newest["comment"] == "lunch #work"


def test_editing_an_entry_shows_its_tags_and_saves_the_changes(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    entry = spa_api.post(
        "/transactions/",
        payee="Cafe",
        tags=["work"],
        postings=[leg(spa_books["food"], "debit", "40"), leg(spa_books["checking"], "credit", "40")],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.get_by_role("button", name="Change the tags")).to_have_text("#work")
    page.get_by_role("button", name="Change the tags").click()
    page.get_by_role("dialog", name="Tags").get_by_role("button", name=re.compile("#work")).click()
    page.get_by_role("button", name="Done").click()
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert spa_api.get(f"/transactions/{entry['id']}")["tags"] == []


def test_repeat_and_edit_from_the_sheet(signed_in_spa_page: Page, spa_books, spa_api: Api):
    page = signed_in_spa_page
    spa_api.post(
        "/transactions/",
        payee="DMart",
        postings=[leg(spa_books["food"], "debit", "1286"), leg(spa_books["checking"], "credit", "1286")],
    )
    page.goto("/transactions")
    page.get_by_role("button", name=re.compile("^DMart")).click()
    page.get_by_role("dialog", name="Transaction details").get_by_role("link", name="Repeat").click()
    page.wait_for_url(re.compile(r"/transactions/new\?repeat="))
    expect(page.get_by_label("Amount")).to_have_value("1,286.00")
    expect(page.get_by_placeholder("Payee or Merchant?")).to_have_value("DMart")
    expect(side(page, "Paid from")).to_contain_text("Checking")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert len([t for t in spa_api.get("/transactions/") if t["payee"] == "DMart"]) == 2
    page.get_by_role("button", name=re.compile("^DMart")).first.click()
    page.get_by_role("dialog", name="Transaction details").get_by_role("link", name="Edit", exact=True).click()
    page.wait_for_url(re.compile(r"/edit$"))
    expect(page.get_by_placeholder("Payee or Merchant?")).to_have_value("DMart")
