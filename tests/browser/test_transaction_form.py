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
    expect(page.locator("a.tx", has_text="DMart")).to_be_visible()
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
    assert amounts(page, "credit") == ["60.00", "40.00"]
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
    assert total.input_value() == "42.00", "the second point is ignored and rupees keep two decimals"
    total.fill("")
    page.keyboard.type("1a2b,5.5x")
    assert total.input_value() == "12,5.5", "letters are ignored, commas and one point stay"
    total.fill("")
    page.keyboard.type("9.999")
    assert total.input_value() == "9.99", "no third decimal for rupees"
    total.fill("")
    page.keyboard.type("--7")
    assert total.input_value() == "-7", "a minus only at the start"


def test_pasting_a_messy_amount_keeps_the_good_part_and_the_cursor(page: Page, books):
    page.goto("/transactions/new")
    total = page.locator("#total")
    total.evaluate("e => { e.focus(); document.execCommand('insertText', false, '1,200.50.25 INR'); }")
    assert total.input_value() == "1,200.50"
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
    page.fill('[data-rows="debit"] [name="amount"]', "2000000")
    expect(page.locator('[data-status="debit"]')).to_contain_text("5,00,000.00 INR over")
    page.fill('[data-rows="debit"] [name="amount"]', "1500000")
    expect(page.locator('[data-status="debit"]')).to_have_text("")  # balanced: nothing is said
    assert page.evaluate("document.documentElement.dataset.grouping") == "indian"


def _spend(api: Api, books, payee: str, amount: str, on: str, **extra):
    return api.post("/transactions/", date=on, payee=payee, postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": amount},
        {"account": books["checking"]["aid"], "side": "credit", "amount": amount},
    ], **extra)


def test_add_related_opens_the_form_linked_and_saves_the_link(page: Page, books, api: Api):
    first = _spend(api, books, "Swiggy", "1000", "2026-10-10")
    page.goto("/transactions")
    page.locator("a.tx", has_text="Swiggy").click()
    page.get_by_role("link", name="Related").click()
    expect(page.locator("[data-related-chip]")).to_contain_text("Swiggy · 10 Oct · 1,000.00")
    expect(page.locator("[data-related-add]")).to_be_hidden()
    assert page.input_value("#total") in ("", "0", "0.00") and page.input_value('input[name="payee"]') == "", "nothing is copied"
    page.fill("#total", "300")
    page.select_option('[data-rows="credit"] select', label="Checking")
    page.select_option('[data-rows="debit"] select', label="Groceries")
    page.fill('input[name="payee"]', "Swiggy cash-back")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [new] = [t for t in api.get("/transactions/") if t["payee"] == "Swiggy cash-back"]
    assert new["related_id"] == first["tid"]
    page.locator("a.tx", has_text="Swiggy").last.click()  # the original now lists it, and the sheet of one opens the other
    expect(page.locator("#txn-sheet .sheet-related-head")).to_have_text("Related · 1")
    page.locator("#txn-sheet .sheet-related-row").click()
    expect(page.locator("#txn-sheet-body h2")).to_have_text("Swiggy cash-back")
    expect(page.locator("#txn-sheet .sheet-related-head")).to_have_text("Related to")


def test_the_picker_relates_an_entry_and_the_chip_removes_it(page: Page, books, api: Api):
    first = _spend(api, books, "Swiggy", "1000", "2026-10-10")
    _spend(api, books, "DMart", "420", "2026-10-11")
    page.goto("/transactions/new")
    expect(page.locator("[data-related-chip]")).to_be_hidden()
    page.locator("[data-related-add]").click()
    expect(page.locator("[data-related-pick]")).to_have_count(2)  # the newest first, once the sheet has loaded
    search = page.locator("#related-picker input[type=search]")
    for attempt in range(4):  # htmx may not have wired the freshly swapped-in field yet (slow WebKit runs): type again
        search.fill("")
        search.fill("swig")
        try:
            expect(page.locator("[data-related-pick]")).to_have_count(1, timeout=1500)
            break
        except AssertionError:
            if attempt == 3:
                raise
    page.locator("[data-related-pick]").click()
    expect(page.locator("#related-picker")).not_to_be_visible()
    expect(page.locator("[data-related-chip]")).to_contain_text("Swiggy")
    assert page.input_value("[data-related-value]") == first["tid"]
    page.locator("[data-related-clear]").click()
    expect(page.locator("[data-related-chip]")).to_be_hidden()
    expect(page.locator("[data-related-add]")).to_be_visible()
    assert page.input_value("[data-related-value]") == ""


def test_from_and_to_are_the_same_size_and_the_swap_sits_between_them(page: Page, books):
    page.goto("/transactions/new")
    page.fill("#total", "100")
    heights = page.eval_on_selector_all(".txn-side", "els => els.map(e => Math.round(e.getBoundingClientRect().height))")
    assert len(heights) == 2 and heights[0] == heights[1], f"the swap button must not make From taller than To: {heights}"
    seam = page.evaluate("""() => {
      const [from, to] = [...document.querySelectorAll('.txn-side')].map(e => e.getBoundingClientRect());
      const b = document.querySelector('[data-swap-sides]').getBoundingClientRect();
      return [b.top + b.height / 2, from.bottom, to.top];
    }""")
    assert seam[1] - 1 <= seam[0] <= seam[2] + 1, f"the button is on the seam between the tiles: {seam}"


def test_an_amount_loses_its_leading_zeros_as_typed_and_gets_its_decimals_when_left(page: Page, books):
    page.goto("/transactions/new")
    total = page.locator("#total")
    total.click()
    page.keyboard.type("007")
    assert total.input_value() == "7", "no zeros in front"
    total.fill("")
    page.keyboard.type("0.5")
    assert total.input_value() == "0.5", "a lone zero before the point stays"
    page.keyboard.press("Tab")
    assert total.input_value() == "0.50", "written out with two decimals on leaving"
    for typed, tidy in (("1.", "1.00"), ("1.1", "1.10"), ("12", "12.00"), (".5", "0.50"), ("1,200", "1200.00")):
        total.fill("")
        total.click()
        page.keyboard.type(typed)
        page.keyboard.press("Tab")
        assert total.input_value() == tidy, typed
    assert page.input_value('[data-rows="debit"] [name="amount"]') == "1200.00", "the rows follow the tidied amount"
    total.fill("")
    total.click()
    page.keyboard.press("Tab")
    assert total.input_value() == "", "an empty amount stays empty"


def test_the_kind_pill_moves_to_the_chosen_button_and_fades_for_other(page: Page, books):
    page.goto("/transactions/new")
    pill = lambda: page.evaluate("""() => { const s = getComputedStyle(document.querySelector('.segmented.kinds'), '::before'); return [new DOMMatrix(s.transform).m41, Number(s.opacity)]; }""")
    assert pill() == [0, 1], "Expense is first"
    page.click('[data-kind="income"]')
    income = pill()
    page.click('[data-kind="transfer"]')
    transfer = pill()
    assert 0 < income[0] < transfer[0] and income[1] == transfer[1] == 1, (income, transfer)
    page.click('[data-kind="transfer"]')  # tapping the chosen one again offers every account
    assert pill()[1] == 0, "no pill for the empty choice"


def test_the_payee_suggestions_stay_on_one_row_on_a_phone_and_a_wide_screen(page: Page, books, api: Api):
    for name in ("Swiggy", "Zomato Gold", "Big Basket", "Blinkit", "Chai Point", "Metro Card", "Pharmacy"):
        history(api, books, payee=name)
    for width in (390, 1280):
        page.set_viewport_size({"width": width, "height": 800})
        page.goto("/transactions/new")
        expect(page.locator("#payee-chips .chip").first).to_be_visible()
        tops = page.eval_on_selector_all("#payee-chips .chip", "els => els.filter(e => e.offsetParent !== null).map(e => e.offsetTop)")
        assert tops and len(set(tops)) == 1, f"every suggestion on one row at {width}px: {tops}"
    expect(page.locator("#payee")).to_have_attribute("placeholder", "Payee or Merchant?")
    page.set_viewport_size({"width": 390, "height": 800})
    page.goto("/transactions/new")
    shown = page.eval_on_selector_all("#payee-chips .chip", "els => els.filter(e => e.offsetParent !== null).length")
    assert 0 < shown < 7, "a phone fits fewer chips than there are habits"
