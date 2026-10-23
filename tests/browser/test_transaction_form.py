"""The transaction form in a browser: the kind buttons, suggestions that follow the total, splitting, new accounts."""

from playwright.sync_api import Page, expect

from .conftest import Api


def groups(page: Page, side: str) -> list[str]:
    return page.eval_on_selector_all(
        f'[data-rows="{side}"] [data-row]:first-child select optgroup', "g => g.map(x => x.label)"
    )


def amounts(page: Page, side: str) -> list[str]:
    return page.eval_on_selector_all(f'[data-rows="{side}"] [name="amount"]', "e => e.map(x => x.value)")


def test_the_kind_buttons_narrow_the_pickers(page: Page, books):
    page.goto("/transactions/new")
    assert (groups(page, "credit"), groups(page, "debit")) == (["Assets", "Liabilities"], ["Expenses"])
    page.get_by_role("button", name="Income", exact=True).click()
    assert (groups(page, "credit"), groups(page, "debit")) == (["Income"], ["Assets", "Liabilities"])
    page.get_by_role("button", name="Transfer", exact=True).click()
    assert groups(page, "credit") == groups(page, "debit") == ["Assets", "Liabilities"]
    page.get_by_role("button", name="Transfer", exact=True).click()  # tapping the selected kind again selects nothing
    expect(page.locator("[data-kind][aria-pressed=true]")).to_have_count(0)
    assert len(groups(page, "credit")) == 5 and len(groups(page, "debit")) == 5, "no kind offers every account"
    page.get_by_role("button", name="Expense", exact=True).click()
    assert (groups(page, "credit"), groups(page, "debit")) == (["Assets", "Liabilities"], ["Expenses"])


def test_the_order_and_the_default(page: Page, books):
    page.goto("/transactions/new")
    labels = page.eval_on_selector_all("[data-kind]", "b => b.map(x => x.textContent)")
    assert labels == ["Expense", "Income", "Transfer"]
    expect(page.locator('[data-kind="expense"]')).to_have_attribute("aria-pressed", "true")


def test_a_choice_survives_a_kind_that_still_offers_it(page: Page, books):
    page.goto("/transactions/new")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.get_by_role("button", name="Transfer", exact=True).click()
    assert page.input_value('[data-rows="credit"] select') == books["checking"]["aid"]
    page.get_by_role("button", name="Income", exact=True).click()
    assert page.input_value('[data-rows="credit"] select') == "", "an asset is not an income source"


def test_saving_an_expense(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.fill("#total", "250")
    assert amounts(page, "credit") == amounts(page, "debit") == ["250.00"], "each side suggests the whole total"
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.fill('input[name="payee"]', "DMart")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    expect(page.get_by_text("DMart")).to_be_visible()
    expect(page.locator("a.tx.tx-new")).to_have_count(1)  # the saved entry's row settles in; only that one
    expect(page.locator("a.tx.tx-new")).to_contain_text("DMart")
    [entry] = [t for t in api.get("/transactions/") if t["payee"] == "DMart"]
    assert {(p["side"], p["amount"]) for p in entry["postings"]} == {("debit", "250.00"), ("credit", "250.00")}
    assert api.get(f"/accounts/{books['food']['aid']}")["balance"] == "250.00"


def test_typing_less_adds_a_row_with_the_remainder(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.click('[data-rows="credit"] [name="amount"]')  # a suggestion is selected on entry: typing replaces it
    page.keyboard.type("60")
    page.keyboard.press("Tab")
    assert amounts(page, "credit") == ["60", "40.00"]
    assert page.eval_on_selector_all('[data-rows="credit"] [name="amount"]', "e => e.map(x => x.classList.contains('suggested'))") == [False, True]
    page.select_option('[data-rows="credit"] [data-row]:nth-child(2) select', label="Cash")
    page.select_option('[data-rows="debit"] select', label="Rent")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = [t for t in api.get("/transactions/") if len(t["postings"]) == 3]
    assert sorted((p["side"], p["amount"]) for p in entry["postings"]) == [
        ("credit", "40.00"), ("credit", "60.00"), ("debit", "100.00"),
    ]


def test_removing_a_row_brings_the_remainder_back(page: Page, books):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    page.fill('[data-rows="debit"] [name="amount"]', "30")
    assert amounts(page, "debit") == ["30", "70.00"]
    page.click('[data-rows="debit"] [data-row]:nth-child(1) [data-remove-row]')
    assert amounts(page, "debit") == ["100.00"]


def test_swapping_from_and_to_offers_every_account(page: Page, books):
    page.goto("/transactions/new")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.click("[data-swap-sides]")
    assert page.input_value('[data-rows="credit"] select') == books["food"]["aid"]
    assert page.input_value('[data-rows="debit"] select') == books["checking"]["aid"]
    expect(page.locator("[data-kind][aria-pressed=true]")).to_have_count(0)  # nothing selected: every account


def test_adding_an_account_from_the_picker(page: Page, books, api: Api):
    page.goto("/transactions/new")
    page.select_option('[data-rows="debit"] select', "__new__")
    dialog = page.locator("#quick-account")
    expect(dialog).to_be_visible()
    dialog.locator('input[name="name"]').fill("Coffee")
    dialog.get_by_role("button", name="Add account").click()
    expect(dialog).not_to_be_visible()
    chosen = page.eval_on_selector('[data-rows="debit"] select', "s => s.selectedOptions[0].textContent")
    assert chosen == "Coffee", "the new account is chosen"
    assert any(a["name"] == "Coffee" for a in api.get("/accounts/"))


def test_editing_keeps_what_was_recorded(page: Page, books, api: Api):
    entry = api.post("/transactions/", payee="Old", postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "40"},
        {"account": books["checking"]["aid"], "side": "credit", "amount": "40"},
    ])
    page.goto(f"/transactions/{entry['tid']}/edit")
    expect(page.locator('[data-kind="expense"]')).to_have_attribute("aria-pressed", "true")
    assert page.input_value("#total") == "40.00" and amounts(page, "credit") == ["40.00"]
    page.fill("#total", "55")
    page.fill('[data-rows="credit"] [name="amount"]', "55")
    page.fill('[data-rows="debit"] [name="amount"]', "55")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url("**/transactions")
    assert api.get(f"/transactions/{entry['tid']}")["postings"][0]["amount"] == "55.00"


def history(api: Api, books, payee="Swiggy", source="card", target="food"):
    api.post("/transactions/", payee=payee, postings=[
        {"account": books[target]["aid"], "side": "debit", "amount": "100"},
        {"account": books[source]["aid"], "side": "credit", "amount": "100"},
    ])


def test_a_payee_chip_fills_both_accounts_and_the_entry_saves_in_three_actions(page: Page, books, api: Api):
    history(api, books)
    page.goto("/transactions/new")
    chip = page.locator("#payee-chips .chip", has_text="Swiggy")
    expect(chip).to_be_visible()
    page.fill("#total", "250")  # 1. the amount
    chip.click()  # 2. who
    assert page.input_value('[data-rows="credit"] select') == books["card"]["aid"]
    assert page.input_value('[data-rows="debit"] select') == books["food"]["aid"]
    assert page.input_value("#payee") == "Swiggy"
    expect(page.locator('[data-kind="expense"]')).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("button", name="Save", exact=True)).to_be_focused()
    page.get_by_role("button", name="Save", exact=True).click()  # 3. save
    page.wait_for_url("**/transactions")
    newest = api.get("/transactions/")[0]
    assert newest["payee"] == "Swiggy" and {p["amount"] for p in newest["postings"]} == {"250.00"}
    assert {(p["account"], p["side"]) for p in newest["postings"]} == {
        (books["card"]["aid"], "credit"), (books["food"]["aid"], "debit")}


def test_the_last_amount_and_the_nudges_fill_the_amount(page: Page, books, api: Api):
    history(api, books)
    page.goto("/transactions/new")
    last = page.locator("[data-last-amount]")
    expect(last).to_be_hidden()
    page.locator("#payee-chips .chip", has_text="Swiggy").click()
    expect(last).to_be_visible()
    expect(last).to_contain_text("as last time")
    last.click()
    amount = page.input_value("#total")
    assert float(amount) > 0
    page.locator('[data-nudge="100"]').click()
    assert float(page.input_value("#total")) == float(amount) + 100
    assert page.input_value('[data-rows="debit"] [name="amount"]').startswith(page.input_value("#total").split(".")[0]), "the rows follow the amount"


def test_a_chip_still_lets_you_split_the_amount_afterwards(page: Page, books, api: Api):
    history(api, books)
    page.goto("/transactions/new")
    page.fill("#total", "900")
    page.locator("#payee-chips .chip", has_text="Swiggy").click()
    page.fill('[data-rows="debit"] [data-row]:nth-child(1) [name="amount"]', "600")
    assert page.locator('[data-rows="debit"] [data-row]').count() == 2, "a row for the rest appears"
    assert page.input_value('[data-rows="debit"] [data-row]:nth-child(2) [name="amount"]') == "300.00"


def test_typing_a_known_payee_fills_the_accounts_without_taking_the_focus(page: Page, books, api: Api):
    history(api, books)
    page.goto("/transactions/new")
    page.select_option('[data-rows="credit"] select', "")
    page.click("#payee")
    page.keyboard.type("swiggy")
    expect(page.locator("#payee-chips .chip[data-exact]")).to_be_visible()
    assert page.input_value('[data-rows="debit"] select') == books["food"]["aid"]
    assert page.evaluate("document.activeElement.id") == "payee", "typing can go on"
    page.keyboard.type(" instamart")
    assert page.input_value("#payee") == "swiggy instamart"


def test_the_chips_narrow_as_you_type(page: Page, books, api: Api):
    history(api, books, "Swiggy")
    history(api, books, "DMart", "checking")
    page.goto("/transactions/new")
    expect(page.locator("#payee-chips .chip")).to_have_count(2)
    page.fill("#payee", "dm")
    expect(page.locator("#payee-chips .chip")).to_have_count(1)
    expect(page.locator("#payee-chips .chip")).to_have_text("DMart")


def test_the_cursor_is_ink_coloured_and_alone_in_an_empty_amount(page: Page, books):
    page.goto("/transactions/new")
    page.focus("#total")
    colours = page.eval_on_selector("#total", "e => [getComputedStyle(e).caretColor, getComputedStyle(e).color]")
    assert colours[0] == colours[1], "the cursor follows the text colour, not the browser's blue"
    if page.context.browser.browser_type.name == "webkit":
        return  # WebKit does not report the style of a ::placeholder; the screenshot check covers it
    placeholder = page.eval_on_selector("#total", "e => getComputedStyle(e, '::placeholder').opacity")
    assert placeholder == "0", "the grey 0.00 steps aside while typing"
    page.evaluate("document.activeElement.blur()")
    assert page.eval_on_selector("#total", "e => getComputedStyle(e, '::placeholder').opacity") != "0"


def test_the_amount_is_focused_on_a_computer_but_not_on_a_phone(page: Page, books):
    page.goto("/transactions/new")
    expect(page.locator("#total")).to_be_focused()
    phone = page.context.browser.new_context(base_url=page.url.split("/transactions")[0], has_touch=True, is_mobile=True, viewport={"width": 390, "height": 844})
    try:
        mobile = phone.new_page()
        mobile.goto("/transactions/new")
        expect(mobile.locator("#total")).not_to_be_focused()
        assert mobile.eval_on_selector("#total", "e => getComputedStyle(e, '::placeholder').opacity") != "0" or mobile.context.browser.browser_type.name == "webkit"
        mobile.tap("#total")
        expect(mobile.locator("#total")).to_be_focused()
    finally:
        phone.close()


def test_an_amount_cannot_be_typed_with_two_decimal_points_or_letters(page: Page, books):
    page.goto("/transactions/new")
    total = page.locator("#total")
    total.click()
    page.keyboard.type("42.00.00")
    assert total.input_value() == "42.0000", "the second point is ignored"
    total.fill("")
    page.keyboard.type("1a2b,5.5x")
    assert total.input_value() == "12,5.5", "letters are ignored, commas and one point stay"
    total.fill("")
    page.keyboard.type("--7")
    assert total.input_value() == "-7", "a minus only at the start"


def test_pasting_a_messy_amount_keeps_the_good_part_and_the_cursor(page: Page, books):
    page.goto("/transactions/new")
    total = page.locator("#total")
    total.evaluate("e => { e.focus(); document.execCommand('insertText', false, '1,200.50.25 INR'); }")
    assert total.input_value() == "1,200.5025"
    total.fill("123")
    total.evaluate("e => { e.focus(); e.setSelectionRange(1, 1); }")
    page.keyboard.type("x4")
    assert total.input_value() == "1423", "the cursor stayed after the 1"


def test_the_budget_sheet_and_other_amount_fields_are_clean_too(page: Page, books):
    page.goto("/budget/move")
    field = page.locator('input[name="amount"]')
    field.click()
    page.keyboard.type("9..9.9")
    assert field.input_value() == "9.99"


def test_the_allocation_status_groups_rupees_in_lakhs(page: Page, books):
    page.goto("/transactions/new")
    page.fill("#total", "1500000")
    page.fill('[data-rows="debit"] [name="amount"]', "500000")
    expect(page.locator('[data-status="debit"]')).to_contain_text("15,00,000.00 INR allocated")
    assert page.evaluate("document.documentElement.dataset.grouping") == "indian"
