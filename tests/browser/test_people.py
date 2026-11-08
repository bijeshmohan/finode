"""People in a real browser: adding someone, lending, sharing a bill with the live result, settling up and undoing."""

import re

from playwright.sync_api import Page, expect

from .conftest import Api, row_button


def alice_of(api: Api, name: str = "Alice") -> dict:
    return api.post("/contacts/", name=name)


def test_add_a_person_and_lend_them_money(page: Page, books, api: Api):
    page.goto("/people")
    page.get_by_role("link", name="Add a person").click()
    page.locator('input[name="name"]').fill("Alice")
    page.get_by_role("button", name="Add person").click()
    page.wait_for_url("**/people/*")
    expect(page.locator("h1")).to_have_text("Alice")
    expect(page.get_by_text("All settled up")).to_be_visible()
    page.get_by_role("link", name="Lend or borrow").click()
    page.locator('input[name="amount"]').fill("500")
    page.locator(".field-pick").first.click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").first.click()
    expect(page.locator(".field-pick").first).to_have_text("Checking")
    page.get_by_role("button", name="Record").click()
    page.wait_for_url("**/people/*")
    expect(page.get_by_text("Alice owes you")).to_be_visible()
    expect(page.locator(".hero-balance")).to_contain_text("500.00")
    assert api.get("/accounts/")  # the books moved: the loan left Checking
    assert float(next(a for a in api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 4500


def test_a_gift_asks_for_a_category_only_when_it_is_a_gift(page: Page, books, api: Api):
    who = alice_of(api)
    page.goto(f"/people/{who['id']}/transfer")
    expect(page.locator('[data-gift="sent"]')).to_be_hidden()
    page.get_by_text("I gave a gift").click()
    expect(page.locator('[data-gift="sent"]')).to_be_visible()
    expect(page.locator('[data-gift="received"]')).to_be_hidden()
    page.get_by_text("They gave me a gift").click()
    expect(page.locator('[data-gift="received"]')).to_be_visible()
    page.get_by_text("I lent money").click()
    expect(page.locator('[data-gift="received"]')).to_be_hidden()


def test_settling_up_shows_what_it_clears_and_asks_about_the_rest(page: Page, books, api: Api):
    who = alice_of(api)
    checking = books["checking"]["id"]
    api.post(
        f"/contacts/{who['id']}/transfers",
        direction="sent",
        purpose="loan",
        amount="500",
        account_id=checking,
        description="Rent help",
    )
    page.goto(f"/people/{who['id']}/settle")
    page.locator(".field-pick").first.click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").first.click()
    page.locator('input[name="amount"]').fill("200")
    expect(page.locator("#settle-preview")).to_contain_text("Rent help")
    expect(page.locator("#settle-preview")).to_contain_text("300.00 left")
    page.locator('input[name="amount"]').fill("800")
    expect(page.locator("#settle-preview")).to_contain_text("is more than is owed")
    page.get_by_role("button", name="Settle up").click()
    expect(page.locator("#form-error")).to_contain_text("say what the rest is")
    page.get_by_text("A gift").click()
    page.get_by_role("button", name="Settle up").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.get_by_text("All settled up")).to_be_visible()


def test_reversing_an_entry_asks_first(page: Page, books, api: Api):
    who = alice_of(api)
    api.post(
        f"/contacts/{who['id']}/transfers",
        direction="sent",
        purpose="loan",
        amount="500",
        account_id=books["checking"]["id"],
    )
    page.goto(f"/people/{who['id']}")
    expect(page.locator(".hero-balance")).to_contain_text("500.00")
    page.locator("a.person-entry").first.click()
    sheet = page.locator("#person-sheet")
    expect(sheet).to_be_visible()
    expect(sheet).to_contain_text("Loan")
    page.once("dialog", lambda dialog: dialog.dismiss())
    sheet.get_by_role("button", name="Reverse").click()
    expect(page.locator(".hero-balance")).to_contain_text("500.00")  # declined: still there
    page.once("dialog", lambda dialog: dialog.accept())
    sheet.get_by_role("button", name="Reverse").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.get_by_text("All settled up")).to_be_visible()


def test_lending_from_the_add_screen_with_a_transfer(page: Page, books, api: Api):
    from .conftest import add_row

    who = alice_of(api)
    page.goto("/transactions/new")
    page.locator('input[name="total"]').fill("300")
    # An income does not offer people; an expense does (a bill can be shared).
    page.get_by_role("button", name="Income", exact=True).click()
    row_button(page, "debit").click()
    expect(page.locator("#row-picker [data-pick-option]", has_text="Alice")).to_have_count(0)
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Transfer").click()
    # People are offered on a transfer only in Split.
    row_button(page, "debit").click()
    expect(page.locator("#row-picker [data-pick-option]", has_text="Alice")).to_have_count(0)
    page.keyboard.press("Escape")
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    add_row(page, "credit", "Checking")
    add_row(page, "debit", "Alice")
    expect(page.locator("[data-person-note]")).to_contain_text("Alice will owe you this")
    page.get_by_role("button", name="Save").click()
    page.wait_for_url("**/transactions")
    assert float(api.get(f"/contacts/{who['id']}")["receivable"]) == 300
    assert float(next(a for a in api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 4700


def test_a_new_person_can_start_with_an_opening_balance(page: Page, books, api: Api):
    page.goto("/people/new")
    page.locator('input[name="name"]').fill("Alice")
    page.get_by_text("Already owes you, or is owed?").click()
    page.locator('input[name="opening_amount"]').fill("4000")
    page.get_by_role("button", name="Add person").click()
    page.wait_for_url("**/people/*")
    expect(page.get_by_text("Alice owes you")).to_be_visible()
    expect(page.locator(".hero-balance")).to_contain_text("4,000.00")
    expect(page.locator("main")).to_contain_text("Opening balance")
    page.locator("details.menu summary").click()
    page.get_by_role("link", name="Add an opening balance").click()
    page.get_by_text("You owe Alice").click()
    page.locator('input[name="opening_amount"]').fill("1000")
    page.get_by_role("button", name="Add opening balance").click()
    page.wait_for_url("**/people/*")
    expect(page.locator(".hero-balance")).to_contain_text("3,000.00")
    assert float(next(a for a in api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 5000


def test_the_figures_carry_the_rupee_sign_and_the_page_has_no_stray_wrapping(page: Page, books, api: Api):
    who = alice_of(api)
    api.post(
        f"/contacts/{who['id']}/transfers",
        direction="sent",
        purpose="loan",
        amount="500",
        account_id=books["checking"]["id"],
    )
    page.goto("/people")
    expect(page.locator(".ready-hero .figure")).to_contain_text("₹")
    page.goto(f"/people/{who['id']}")
    expect(page.locator(".hero-balance")).to_contain_text("₹")
    buttons = page.locator(".person-actions .button")
    assert buttons.count() == 3
    tops = {round(buttons.nth(i).bounding_box()["y"]) for i in range(3)}
    assert len(tops) == 1, "Add expense, Lend or borrow and Settle up are on one row"
    page.goto(f"/people/{who['id']}/settle")
    label = page.locator("label", has_text="Note").first
    assert label.bounding_box()["height"] < 80, "the label's '(optional)' stays beside it, not under it"
    page.locator('input[name="amount"]').fill("100")
    heading = page.locator(".preview-head").first
    expect(heading).to_be_visible()
    assert heading.evaluate("e => getComputedStyle(e).textTransform") == "none"


def test_an_opening_balance_can_be_edited_from_its_sheet(page: Page, books, api: Api):
    who = alice_of(api)
    entry = api.post(f"/contacts/{who['id']}/opening-balance", direction="receivable", amount="4000", date="2026-01-01")
    page.goto(f"/people/{who['id']}")
    page.locator("a.person-entry").first.click()
    page.locator("#person-sheet").get_by_role("link", name="Edit").click()
    page.wait_for_url(f"**/opening/{entry['id']}/edit")
    page.locator('input[name="opening_amount"]').fill("2500")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.locator(".hero-balance")).to_contain_text("2,500.00")


def test_an_expense_can_be_edited_into_a_loan_and_back(page: Page, books, api: Api):
    who = alice_of(api)
    entry = api.post(
        "/transactions/",
        payee="Cab",
        postings=[
            {"category_id": books["food"]["id"], "side": "debit", "amount": "300"},
            {"account_id": books["checking"]["id"], "side": "credit", "amount": "300"},
        ],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    row_button(page, "debit").click()
    page.locator("#row-picker [data-pick-option]", has_text="Alice").first.click()
    expect(page.locator("[data-person-note]")).to_contain_text("Alice will owe you this")
    page.get_by_role("button", name="Save").click()
    page.wait_for_url(lambda url: "/edit" not in url)
    assert float(api.get(f"/contacts/{who['id']}")["receivable"]) == 300
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(row_button(page, "debit")).to_contain_text("Alice")
    page.get_by_role("button", name="Expense", exact=True).click()
    row_button(page, "debit").click()
    page.locator("#row-picker [data-pick-option]", has_text="Groceries").first.click()
    page.get_by_role("button", name="Save").click()
    page.wait_for_url(lambda url: "/edit" not in url)
    assert float(api.get(f"/contacts/{who['id']}")["net"]) == 0


def test_netting_off_what_two_people_owe_each_other(page: Page, books, api: Api):
    who = alice_of(api)
    checking = books["checking"]["id"]
    api.post(f"/contacts/{who['id']}/transfers", direction="sent", purpose="loan", amount="23000", account_id=checking)
    api.post(
        f"/contacts/{who['id']}/transfers",
        direction="received",
        purpose="borrowing",
        amount="23000",
        account_id=checking,
    )
    page.goto("/people")
    expect(page.locator("a.crow").first).to_contain_text("Even · 23,000.00 each way")
    page.locator("a.crow").first.click()
    page.get_by_role("link", name="Net off 23,000.00").click()
    expect(page.locator("main")).to_contain_text("Afterwards neither owes the other anything")
    page.get_by_role("button", name="Net off 23,000.00").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.get_by_text("All settled up")).to_be_visible()
    expect(page.locator('a[href$="/netoff"]')).to_have_count(0)


def pick(page: Page, index: int, label: str) -> None:
    """Choose in the sheet behind the nth field of the Split tab (0: the category, 1: the account you paid from)."""
    page.locator(".people-editor .field-pick").nth(index).click()
    page.locator("#row-picker [data-pick-option]", has_text=label).first.click()


def test_the_two_ways_show_and_hide_what_they_should(page: Page, books, api: Api):
    alice_of(api)
    page.goto("/transactions/new")
    modes = page.locator("[data-modes]")
    expect(modes).to_be_visible()
    expect(page.locator("form[data-txn-form]")).to_have_attribute("data-mode", "simple")
    expect(page.locator('[data-people-editor="expense"]')).to_be_hidden()
    expect(page.locator('[data-side-section="credit"]')).to_be_visible()
    modes.get_by_text("Split", exact=True).click()
    expect(page.locator('[data-people-editor="expense"]')).to_be_visible()
    expect(page.locator('[data-side-section="credit"]')).to_be_hidden()
    expect(page.locator('[data-side-section="debit"]')).to_be_hidden()
    page.get_by_role("button", name="Income", exact=True).click()
    expect(page.locator('[data-people-editor="income"]')).to_be_visible()  # Split stays, with the income's own tab
    expect(page.locator('[data-people-editor="expense"]')).to_be_hidden()
    page.get_by_role("button", name="Transfer", exact=True).click()
    expect(modes).to_be_visible()
    expect(page.locator("form[data-txn-form]")).to_have_attribute("data-mode", "simple")  # back to the rows
    expect(page.locator("[data-people-editor]")).to_have_count(2)
    expect(page.locator('[data-people-editor="income"]')).to_be_hidden()
    expect(page.locator('[data-side-section="credit"]')).to_be_visible()
    modes.get_by_text("Split", exact=True).click()
    expect(page.locator('[data-people-editor="expense"]')).to_be_hidden()  # a transfer in Split keeps its rows
    expect(page.locator('[data-side-section="credit"]')).to_be_visible()
    page.get_by_role("button", name="Expense", exact=True).click()
    expect(page.locator("form[data-txn-form]")).to_have_attribute("data-mode", "simple")


def test_typing_less_than_the_total_adds_a_row_and_shows_what_is_left(page: Page, books, api: Api):
    from .conftest import add_row

    page.goto("/transactions/new")
    page.locator('input[name="total"]').fill("1000")
    form = page.locator("form[data-txn-form]")
    expect(form).to_have_attribute("data-layout", "single")
    add_row(page, "credit", "Checking")
    add_row(page, "debit", "Groceries", amount="600")
    expect(form).to_have_attribute("data-layout", "multi")
    expect(form).to_have_attribute("data-mode", "simple")  # more rows is still Simple: Split is for people
    assert page.locator('[data-rows="debit"] [data-row]').count() == 2
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    page.locator("[data-modes]").get_by_text("Simple", exact=True).click()
    assert page.locator('[data-rows="debit"] [data-row]').count() == 2, "the rows are kept"


def test_a_bill_shared_from_the_with_people_tab_shows_its_result_as_you_type(page: Page, books, api: Api):
    who, bob = alice_of(api), alice_of(api, "Bob")
    page.goto(f"/transactions/new?mode=split&with={who['id']}")
    expect(page.locator(f'input[name="with_{who["id"]}"]')).to_be_checked()
    page.locator('input[name="total"]').fill("900")
    page.locator('input[name="payee"]').fill("Dinner")
    pick(page, 0, "Groceries")
    pick(page, 1, "Checking")
    preview = page.locator("#people-preview")
    expect(preview).to_contain_text("Alice owes you")
    expect(preview).to_contain_text("450.00")
    page.locator(f'input[name="with_{bob["id"]}"]').check()
    expect(preview).to_contain_text("Bob owes you")
    expect(preview).to_contain_text("300.00")
    page.locator(".people-editor").get_by_text("%", exact=True).click()
    page.locator('input[name="value_self"]').fill("50")
    page.locator(f'input[name="value_{who["id"]}"]').fill("30")
    page.locator(f'input[name="value_{bob["id"]}"]').fill("20")
    expect(preview).to_contain_text("270.00")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert float(api.get(f"/contacts/{who['id']}")["receivable"]) == 270
    assert float(api.get(f"/contacts/{bob['id']}")["receivable"]) == 180


def test_switching_to_with_people_carries_over_what_the_rows_already_say(page: Page, books, api: Api):
    from .conftest import add_row

    alice, bob = alice_of(api), alice_of(api, "Bob")
    page.goto("/transactions/new")
    page.locator('input[name="total"]').fill("1500")
    page.locator('input[name="payee"]').fill("Dinner")
    add_row(page, "credit", "Checking")
    add_row(page, "debit", "Groceries")
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    expect(page.locator(".people-editor .field-pick").nth(0)).to_have_text("Groceries")
    expect(page.locator(".people-editor .field-pick").nth(1)).to_have_text("Checking")
    page.locator(f'input[name="with_{alice["id"]}"]').check()
    page.locator(f'input[name="with_{bob["id"]}"]').check()
    expect(page.locator("#people-preview")).to_contain_text("500.00")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert float(api.get(f"/contacts/{alice['id']}")["receivable"]) == 500
    assert float(next(a for a in api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 3500


def test_a_friend_who_paid_can_be_recorded_from_the_tab(page: Page, books, api: Api):
    alice = alice_of(api)
    page.goto(f"/transactions/new?mode=split&with={alice['id']}")
    page.locator('input[name="total"]').fill("1000")
    pick(page, 0, "Groceries")
    page.locator(".people-editor summary", has_text="Someone else paid").click()
    page.locator('input[name="paid_self"]').fill("0")
    page.locator(f'input[name="paid_{alice["id"]}"]').fill("1000")
    expect(page.locator("#people-preview")).to_contain_text("Alice")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    got = api.get(f"/contacts/{alice['id']}")
    assert float(got["payable"]) == 500 and float(got["receivable"]) == 0


def test_the_with_people_rows_sit_in_a_line(page: Page, books, api: Api):
    who = alice_of(api)
    page.goto(f"/transactions/new?mode=split&with={who['id']}")
    rows = page.locator('[data-people-editor="expense"] .share-row')
    assert rows.count() == 2
    for index in range(2):
        row = rows.nth(index)
        box, check, name = (
            row.bounding_box(),
            row.locator('input[type="checkbox"]').bounding_box(),
            row.locator(".crow-name").bounding_box(),
        )
        assert box and check and name
        assert abs((check["y"] + check["height"] / 2) - (name["y"] + name["height"] / 2)) < 6
        assert box["height"] < 70
    expect(rows.first.locator('input[type="checkbox"]')).to_be_disabled()
    page.locator(".people-editor").get_by_text("%", exact=True).click()
    expect(rows.nth(1).locator(".share-value")).to_be_visible()


def test_an_old_expense_can_be_edited_into_a_shared_bill(page: Page, books, api: Api):
    alice, bob = alice_of(api), alice_of(api, "Bob")
    entry = api.post(
        "/transactions/",
        payee="Restaurant",
        date="2026-10-09",
        postings=[
            {"category_id": books["food"]["id"], "side": "debit", "amount": "3000"},
            {"account_id": books["checking"]["id"], "side": "credit", "amount": "3000"},
        ],
    )
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.locator("form[data-txn-form]")).to_have_attribute("data-mode", "simple")
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    expect(page.locator(".people-editor .field-pick").nth(0)).to_have_text("Groceries")
    page.locator(f'input[name="with_{alice["id"]}"]').check()
    page.locator(f'input[name="with_{bob["id"]}"]').check()
    expect(page.locator("#people-preview")).to_contain_text("1,000.00")
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(lambda u: "/edit" not in u)
    assert float(api.get(f"/contacts/{alice['id']}")["receivable"]) == 1000
    assert api.get(f"/transactions/{entry['id']}")["date"] == "2026-10-09"
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.locator("form[data-txn-form]")).to_have_attribute("data-mode", "split")
    expect(page.locator(f'input[name="with_{bob["id"]}"]')).to_be_checked()


def test_income_shared_with_a_person_from_the_add_screen(page: Page, books, api: Api):
    who = alice_of(api)
    page.goto("/transactions/new")
    page.get_by_role("button", name="Income", exact=True).click()
    expect(page.locator('[data-side-section="credit"] [data-side-title]')).to_have_text("Earned from")
    expect(page.locator('[data-side-section="debit"] [data-side-title]')).to_have_text("Paid into")
    page.locator('input[name="total"]').fill("10000")
    page.locator('input[name="payee"]').fill("Rent, Flat 4B")
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    editor = page.locator('[data-people-editor="income"]')
    expect(editor).to_be_visible()
    editor.locator(".field-pick").nth(0).click()
    page.locator("#row-picker [data-pick-option]", has_text="Salary").first.click()
    editor.locator(".field-pick").nth(1).click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").first.click()
    page.locator(f'input[name="theirs_{who["id"]}"]').fill("4000")
    preview = page.locator("#income-preview")
    expect(preview).to_contain_text("Your income")
    expect(preview).to_contain_text("6,000.00")
    expect(preview).to_contain_text("you hold it for them")
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url(re.compile(r"/transactions(\?|$)"))
    assert float(api.get(f"/contacts/{who['id']}")["payable"]) == 4000
    assert float(next(a for a in api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 15000
    entry = next(t for t in api.get("/transactions/") if t["payee"] == "Rent, Flat 4B")
    page.goto(f"/transactions/{entry['id']}/edit")
    expect(page.locator("form[data-txn-form]")).to_have_attribute("data-mode", "split")
    expect(page.locator(f'input[name="theirs_{who["id"]}"]')).to_have_value("4000.00")


def test_the_mode_switch_looks_and_moves_like_the_kind_switch(page: Page, books, api: Api):
    alice_of(api)
    page.goto("/transactions/new")
    look = """(sel) => {
        const el = document.querySelector(sel);
        const on = el.querySelector('[aria-pressed="true"], input:checked');
        const chosen = on.closest('label') || on;
        const pill = getComputedStyle(el, '::before');
        return {radius: getComputedStyle(el).borderRadius, colour: getComputedStyle(chosen).color,
                weight: getComputedStyle(chosen).fontWeight, pill: pill.transform, shadow: pill.boxShadow};
    }"""
    kinds, modes = page.evaluate(look, ".segmented.kinds"), page.evaluate(look, "[data-modes]")
    assert kinds["radius"] == modes["radius"] and kinds["colour"] == modes["colour"]
    assert kinds["weight"] == modes["weight"] and kinds["shadow"] == modes["shadow"]
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    page.wait_for_function(
        "() => getComputedStyle(document.querySelector('[data-modes]'), '::before').transform !== 'matrix(1, 0, 0, 1, 0, 0)'"
    )
    page.locator('[data-people-editor="expense"] .scope-seg').get_by_text("%", exact=True).click()
    assert (
        page.evaluate(
            "() => getComputedStyle(document.querySelector('[data-people-editor=expense] .scope-seg'), '::before').transform"
        )
        != "matrix(1, 0, 0, 1, 0, 0)"
    )
