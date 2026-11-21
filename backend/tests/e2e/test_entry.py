"""The React app's Add and Edit screen in a browser (ports of test_transaction_form.py, test_account_picker.py,
test_row_category.py and test_tags.py for what the Simple form does)."""

import re

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api
from .test_home import MUTED


def side(page: Page, title: str):
    return page.locator("main").get_by_role("button", name=re.compile(f"^{title}"))


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


def test_the_kind_buttons_narrow_the_pickers(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    assert (offered(page, "Paid from"), offered(page, "Spent on")) == (["Assets", "Liabilities"], ["Expenses"])
    page.get_by_role("button", name="Income", exact=True).click()
    assert (offered(page, "Earned from"), offered(page, "Paid into")) == (["Income"], ["Assets", "Liabilities"])
    page.get_by_role("button", name="Transfer", exact=True).click()
    assert offered(page, "From") == ["Assets", "Liabilities"]
    page.get_by_role("button", name="Transfer", exact=True).click()  # tapping the selected kind again selects nothing
    expect(page.locator("[aria-pressed=true]", has_text="Transfer")).to_have_count(0)
    assert len(offered(page, "From")) == 5, "no kind offers every account"


def test_the_order_and_the_default(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    kinds = page.get_by_role("group", name=re.compile("What kind of entry")).get_by_role("button")
    expect(kinds).to_have_count(3)
    assert kinds.all_inner_texts() == ["Expense", "Income", "Transfer"]
    expect(page.get_by_role("button", name="Expense", exact=True)).to_have_attribute("aria-pressed", "true")


def test_a_choice_survives_a_kind_that_still_offers_it(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    choose(page, "Paid from", "Checking")
    page.get_by_role("button", name="Transfer", exact=True).click()
    expect(side(page, "From")).to_contain_text("Checking")
    page.get_by_role("button", name="Income", exact=True).click()
    expect(side(page, "Earned from")).not_to_contain_text("Checking"), "an asset is not an income source"


def test_saving_an_expense(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("250")
    choose(page, "Paid from", "Checking")
    choose(page, "Spent on", "Groceries")
    page.get_by_placeholder("Payee or Merchant?").fill("DMart")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    expect(page.get_by_role("button", name=re.compile("^DMart"))).to_be_visible()
    [entry] = [t for t in api.get("/transactions/") if t["payee"] == "DMart"]
    assert {(p["side"], p["amount"]) for p in entry["postings"]} == {("debit", "250.00"), ("credit", "250.00")}


def test_swapping_from_and_to_keeps_a_transfer_and_an_expense_has_no_swap(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    expect(page.get_by_role("button", name="Swap From and To")).to_have_count(0)
    page.get_by_role("button", name="Transfer", exact=True).click()
    choose(page, "From", "Checking")
    choose(page, "To", "Cash")
    page.get_by_role("button", name="Swap From and To").click()
    expect(side(page, "From")).to_contain_text("Cash")
    expect(side(page, "To")).to_contain_text("Checking")
    expect(page.get_by_role("button", name="Transfer", exact=True)).to_have_attribute("aria-pressed", "true")


def test_editing_keeps_what_was_recorded(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    entry = api.post(
        "/transactions/",
        payee="Old",
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.get_by_role("button", name="Expense", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_label("Amount", exact=True)).to_have_value("40.00")
    page.get_by_label("Amount", exact=True).fill("55")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert {p["amount"] for p in api.get(f"/transactions/{entry['id']}")["postings"]} == {"55.00"}


def test_deleting_from_the_edit_screen_goes_back_to_the_list(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    entry = api.post(
        "/transactions/",
        payee="Gone",
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
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


def test_a_payee_chip_fills_the_payee_only_and_moves_on_to_the_amount(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    history(api, books)
    page.goto("/transactions/new")
    expect(chips(page)).to_have_count(0)
    page.get_by_placeholder("Payee or Merchant?").fill("sw")
    chips(page).filter(has_text="Swiggy").click()
    expect(page.get_by_placeholder("Payee or Merchant?")).to_have_value("Swiggy")
    expect(chips(page)).to_have_count(0)
    expect(side(page, "Paid from")).to_contain_text("Account…")
    expect(page.get_by_label("Amount", exact=True)).to_be_focused()


def test_the_chips_narrow_as_you_type(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    history(api, books, "Swiggy")
    history(api, books, "DMart", "checking")
    page.goto("/transactions/new")
    page.get_by_placeholder("Payee or Merchant?").fill("dm")
    expect(chips(page)).to_have_count(1)
    expect(chips(page)).to_have_text("DMart")
    page.get_by_placeholder("Payee or Merchant?").fill("")
    expect(chips(page)).to_have_count(0)


def test_the_amount_is_focused_on_a_computer_but_not_on_a_phone(signed_in_page: Page, books, browser, server):
    page = signed_in_page
    page.goto("/transactions/new")
    expect(page.get_by_label("Amount", exact=True)).to_be_focused()  # the test page has a mouse
    phone = browser.new_context(viewport={"width": 390, "height": 844}, base_url=server, has_touch=True, is_mobile=True)
    try:
        phone.add_cookies(page.context.cookies())
        mobile = phone.new_page()
        mobile.goto("/transactions/new")
        expect(mobile.get_by_label("Amount", exact=True)).to_be_visible()
        expect(mobile.get_by_label("Amount", exact=True)).not_to_be_focused()
    finally:
        phone.close()


def test_an_amount_cannot_be_typed_with_two_decimal_points_or_letters(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    amount = page.get_by_label("Amount", exact=True)
    amount.press_sequentially("12a.3.45")
    expect(amount).to_have_value("12.34")


def test_the_amount_is_grouped_as_it_is_typed_and_the_cursor_stays(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    page.goto("/transactions/new")
    amount = page.get_by_label("Amount", exact=True)
    amount.press_sequentially("1234567")
    expect(amount).to_have_value(re.compile(r"^(12,34,567|1,234,567)$"))
    assert amount.evaluate("e => e.selectionStart") == len(amount.input_value())


def test_add_related_opens_the_form_linked_and_saves_the_link(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    first = api.post(
        "/transactions/",
        payee="Amazon",
        postings=[leg(books["food"], "debit", "4998"), leg(books["card"], "credit", "4998")],
    )
    page.goto(f"/transactions/new?related={first['id']}")
    expect(page.get_by_text("Related to")).to_be_visible()
    page.get_by_label("Amount", exact=True).fill("1000")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.get_by_role("button", name="Transfer", exact=True).click()  # every account
    choose(page, "From", "Groceries")
    choose(page, "To", "Visa")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert any(t.get("related_id") == first["id"] for t in api.get("/transactions/"))


def test_the_picker_relates_an_entry_and_the_chip_removes_it(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    history(api, books, "Amazon")
    page.goto("/transactions/new")
    page.get_by_role("button", name="Related").click()
    page.get_by_label("Search transactions").fill("ama")
    page.get_by_role("dialog", name="Related to…").get_by_role("button", name=re.compile("Amazon")).click()
    expect(page.get_by_text("Related to")).to_be_visible()
    page.get_by_role("button", name="Remove the link").click()
    expect(page.get_by_role("button", name="Related")).to_be_visible()


def test_the_date_is_a_chip_that_names_the_day(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    expect(page.get_by_label("Date").locator("xpath=..")).to_contain_text(re.compile(r"^Today, \d{1,2} \w{3}"))


def test_an_account_is_chosen_in_a_sheet_and_the_other_side_is_greyed(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    page.get_by_role("button", name="Transfer", exact=True).click()
    choose(page, "From", "Checking")
    side(page, "To").click()
    sheet = page.get_by_role("dialog", name="To")
    expect(sheet.get_by_role("button", name=re.compile("Checking"))).to_be_disabled()
    expect(sheet.get_by_role("button", name=re.compile("Cash"))).to_be_enabled()


def test_the_chosen_account_is_bold(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    choose(page, "Paid from", "Checking")
    side(page, "Paid from").click()
    chosen = page.get_by_role("dialog", name="Paid from").get_by_role("button", name=re.compile("Checking"))
    expect(chosen).to_have_attribute("aria-pressed", "true")
    assert int(chosen.evaluate("e => getComputedStyle(e).fontWeight")) >= 600


def test_pressing_an_option_keeps_the_search_focused_so_the_sheet_does_not_move(signed_in_page: Page, books):
    page = signed_in_page
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


def test_the_category_line_shows_only_when_money_leaves_the_budget(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    loan = api.post("/accounts/", name="Home Loan", parent_id=books["roots"]["Liabilities"], on_budget=False)
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


def test_choosing_tags_and_making_a_new_one(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    page.goto("/transactions/new")
    page.get_by_label("Amount", exact=True).fill("12")
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
    newest = api.get("/transactions/")[0]
    assert newest["tags"] == ["goa-trip"] and newest["comment"] == "lunch #work"


def test_editing_an_entry_shows_its_tags_and_saves_the_changes(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    entry = api.post(
        "/transactions/",
        payee="Cafe",
        tags=["work"],
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.get_by_role("button", name="Change the tags")).to_have_text("#work")
    page.get_by_role("button", name="Change the tags").click()
    page.get_by_role("dialog", name="Tags").get_by_role("button", name=re.compile("#work")).click()
    page.get_by_role("button", name="Done").click()
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert api.get(f"/transactions/{entry['id']}")["tags"] == []


def test_repeat_and_edit_from_the_sheet(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    api.post(
        "/transactions/",
        payee="DMart",
        postings=[leg(books["food"], "debit", "1286"), leg(books["checking"], "credit", "1286")],
    )
    page.goto("/transactions")
    page.get_by_role("button", name=re.compile("^DMart")).click()
    page.get_by_role("dialog", name="Transaction details").get_by_role("link", name="Repeat").click()
    page.wait_for_url(re.compile(r"/transactions/new\?repeat="))
    expect(page.get_by_label("Amount", exact=True)).to_have_value("1,286.00")
    expect(page.get_by_placeholder("Payee or Merchant?")).to_have_value("DMart")
    expect(side(page, "Paid from")).to_contain_text("Checking")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert len([t for t in api.get("/transactions/") if t["payee"] == "DMart"]) == 2
    page.get_by_role("button", name=re.compile("^DMart")).first.click()
    page.get_by_role("dialog", name="Transaction details").get_by_role("link", name="Edit", exact=True).click()
    page.wait_for_url(re.compile(r"/edit\?back="))
    expect(page.get_by_placeholder("Payee or Merchant?")).to_have_value("DMart")


def test_a_new_account_can_be_made_from_the_sheet(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    page.goto("/transactions/new")
    side(page, "Paid from").click()
    page.get_by_role("dialog", name="Paid from").get_by_role("button", name="＋ New account").click()
    sheet = page.get_by_role("dialog", name="New account")
    expect(sheet).to_be_visible()
    sheet.get_by_label("Name").fill("Kotak")
    sheet.get_by_role("button", name="Add account").click()
    expect(sheet).to_have_count(0)
    expect(side(page, "Paid from")).to_contain_text("Kotak")
    assert any(a["name"] == "Kotak" for a in api.get("/accounts/"))


def test_adding_a_category_from_the_picker(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    page.goto("/transactions/new")
    side(page, "Spent on").click()
    page.get_by_role("dialog", name="Spent on").get_by_role("button", name="＋ New category").click()
    sheet = page.get_by_role("dialog", name="New category")
    sheet.get_by_label("Name").fill("Coffee")
    sheet.get_by_role("button", name="Add category").click()
    expect(sheet).to_have_count(0)
    expect(side(page, "Spent on")).to_contain_text("Coffee")
    assert any(c["name"] == "Coffee" for c in api.get("/categories/"))


def test_the_amount_is_a_bare_figure_with_the_rupee_sign_against_it(signed_in_page: Page, books):
    """No box and no ring around the Add screen's amount; the sign muted and right against the digits."""
    app = signed_in_page
    app.goto("/transactions/new")
    field = app.get_by_label("Amount", exact=True)
    field.focus()
    field.fill("250")
    look = field.evaluate(
        "e => { const s = getComputedStyle(e); return [s.borderTopWidth, s.outlineStyle, s.boxShadow]; }"
    )
    assert look == ["0px", "none", "none"], look
    sign = app.locator("main").get_by_text("₹", exact=True).first
    assert sign.evaluate("e => getComputedStyle(e).color") == app.evaluate(MUTED), "muted"
    sign_box, field_box = sign.bounding_box(), field.bounding_box()
    assert sign_box and field_box
    assert 0 <= field_box["x"] - (sign_box["x"] + sign_box["width"]) <= 16, "the sign sits against the digits"
    assert field_box["width"] < 200, "the field is as wide as what is typed"


GLYPH = """(e) => { const b = getComputedStyle(e, '::before');
  return {content: b.content, dashed: b.borderTopStyle, mask: b.maskImage || b.webkitMaskImage, weight: getComputedStyle(e).fontWeight}; }"""


def test_the_rows_read_a_plus_until_chosen_then_a_glyph(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/transactions/new")
    for title in ("Paid from", "Spent on"):
        empty = side(page, title).evaluate(GLYPH)
        assert (empty["content"], empty["dashed"]) == ('"+"', "dashed"), (title, empty)
        assert side(page, title).locator("svg").count() == 0, "no chevron"
    choose(page, "Paid from", "Checking")
    choose(page, "Spent on", "Groceries")
    account, category = side(page, "Paid from").evaluate(GLYPH), side(page, "Spent on").evaluate(GLYPH)
    assert "M3 10l9-6" in account["mask"], "a bank for an account"
    assert "M3 12V4h8" in category["mask"], "a tag for a category"
    assert account["weight"] == "600"
