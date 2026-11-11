"""People in a real browser: adding someone, the pills that open the new screen, the note under the form, sharing a bill with the live result and undoing."""

import re

from playwright.sync_api import Page, expect

from .conftest import Api, add_row, row_button


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
    page.get_by_role("link", name="Lend", exact=True).click()
    page.locator('input[name="total"]').fill("500")
    expect(row_button(page, "debit")).to_contain_text("Alice")  # the pill filled the person in
    add_row(page, "credit", "Checking")
    expect(page.locator("[data-person-note]")).to_contain_text("Alice will owe you this")
    page.get_by_role("button", name="Save").click()
    page.wait_for_url("**/people/*")
    expect(page.get_by_text("Alice owes you")).to_be_visible()
    expect(page.locator(".hero-balance")).to_contain_text("500.00")
    assert api.get("/accounts/")  # the books moved: the loan left Checking
    assert float(next(a for a in api.get("/accounts/") if a["name"] == "Checking")["balance"]) == 4500


def test_settle_opens_the_new_screen_with_what_is_owed_and_the_note_follows_the_amount(page: Page, books, api: Api):
    who = alice_of(api)
    api.post(
        f"/contacts/{who['id']}/transfers",
        direction="sent",
        purpose="loan",
        amount="500",
        account_id=books["checking"]["id"],
    )
    page.goto(f"/people/{who['id']}")
    page.get_by_role("link", name="Settle", exact=True).click()
    page.wait_for_url("**/transactions/new**")
    expect(page.locator('input[name="total"]')).to_have_value("500.00")
    expect(row_button(page, "credit")).to_contain_text("Alice")  # they pay you back
    expect(page.locator("[data-person-note]")).to_contain_text("Alice pays back in full")
    page.locator('input[name="total"]').fill("200")
    expect(page.locator("[data-person-note]")).to_contain_text("Alice pays back 200.00 of the 500.00")
    page.locator('input[name="total"]').fill("800")
    expect(page.locator("[data-person-note]")).to_contain_text("The other 300.00 is borrowed")
    add_row(page, "debit", "Checking")
    page.get_by_role("button", name="Save").click()
    page.wait_for_url(f"**/people/{who['id']}")
    expect(page.get_by_text("You owe Alice")).to_be_visible()
    expect(page.locator(".hero-balance")).to_contain_text("300.00")


def test_an_at_sign_in_the_payee_names_a_person_and_typing_over_it_takes_them_off(page: Page, books, api: Api):
    who = alice_of(api)
    page.goto("/transactions/new")
    page.locator('input[name="payee"]').fill("@Al")
    page.locator("#payee-chips .chip", has_text="Alice").click()
    expect(page.locator('input[name="payee"]')).to_have_value("Alice")
    expect(page.locator("[data-payee-person]")).to_contain_text("Saved in Alice's activity")
    page.locator('input[name="payee"]').press("End")
    page.locator('input[name="payee"]').type("x")
    expect(page.locator("[data-payee-person]")).to_be_hidden()
    page.locator('input[name="payee"]').fill("@Al")
    page.locator("#payee-chips .chip", has_text="Alice").click()
    page.locator('input[name="total"]').fill("250")
    add_row(page, "credit", "Checking")
    add_row(page, "debit", "Groceries")
    page.get_by_role("button", name="Transfer", exact=True).click()
    expect(page.locator("[data-payee-person]")).to_be_hidden()  # only an expense or an income can name a person
    page.get_by_role("button", name="Expense", exact=True).click()
    page.locator('input[name="payee"]').fill("@A")
    page.locator("#payee-chips .chip", has_text="Alice").click()
    add_row(page, "debit", "Groceries")
    page.get_by_role("button", name="Save").click()
    page.wait_for_url("**/transactions")
    gifts = api.get(f"/contacts/{who['id']}/activity?purpose=gift")
    assert gifts["total"] == 1 and float(api.get(f"/contacts/{who['id']}")["net"]) == 0


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
    who = alice_of(api)
    page.goto("/transactions/new")
    page.locator('input[name="total"]').fill("300")
    # An income does not offer people; an expense does (a bill can be shared).
    page.get_by_role("button", name="Income", exact=True).click()
    row_button(page, "debit").click()
    expect(page.locator("#row-picker [data-pick-option]", has_text="Alice")).to_have_count(0)
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Transfer").click()
    # People are offered on a transfer, with no Split to choose.
    expect(page.locator("[data-modes]")).to_be_hidden()
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
    assert buttons.count() == 4
    tops = {round(buttons.nth(i).bounding_box()["y"]) for i in range(4)}
    assert len(tops) == 1, "Expense, Lend, Borrow and Settle are on one row"


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


def test_what_two_people_owe_each_other_evens_out_by_itself(page: Page, books, api: Api):
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
    expect(page.locator("a.crow").first).not_to_contain_text("each way")
    page.locator("a.crow").first.click()
    expect(page.get_by_text("All settled up")).to_be_visible()
    expect(page.locator("main")).to_contain_text("Evened out")


def add_people(page: Page, *names: str, kind: str = "expense") -> None:
    """Add people to a Split from the sheet behind "Add people"."""
    page.locator(f'[data-people-editor="{kind}"] [data-add-people]').click()
    for name in names:
        page.locator("#people-picker [data-people-option]", has_text=name).click()
    page.locator("#people-picker [data-people-done]").click()


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
    expect(modes).to_be_hidden()  # a transfer has no Split: people are simply on its rows
    expect(page.locator("form[data-txn-form]")).to_have_attribute("data-mode", "simple")  # back to the rows
    expect(page.locator("[data-people-editor]")).to_have_count(2)
    expect(page.locator('[data-people-editor="income"]')).to_be_hidden()
    expect(page.locator('[data-side-section="credit"]')).to_be_visible()
    page.get_by_role("button", name="Expense", exact=True).click()
    expect(modes).to_be_visible()
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
    add_people(page, "Bob")
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

    alice = alice_of(api)
    alice_of(api, "Bob")
    page.goto("/transactions/new")
    page.locator('input[name="total"]').fill("1500")
    page.locator('input[name="payee"]').fill("Dinner")
    add_row(page, "credit", "Checking")
    add_row(page, "debit", "Groceries")
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    expect(page.locator(".people-editor .field-pick").nth(0)).to_have_text("Groceries")
    expect(page.locator(".people-editor .field-pick").nth(1)).to_have_text("Checking")
    add_people(page, "Alice", "Bob")
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
    names = [rows.nth(i).locator(".crow-name").bounding_box() for i in range(2)]
    assert names[0] and names[1] and abs(names[0]["x"] - names[1]["x"]) < 2, "the names line up"
    for index in range(2):
        box = rows.nth(index).bounding_box()
        assert box and box["height"] < 70
    remove, name = rows.nth(1).locator("[data-person-remove]").bounding_box(), names[1]
    assert remove and name and abs((remove["y"] + remove["height"] / 2) - (name["y"] + name["height"] / 2)) < 6
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
    add_people(page, "Alice", "Bob")
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
    add_people(page, "Alice", kind="income")
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


def test_only_the_people_added_are_listed_and_the_sheet_adds_and_removes_them(page: Page, books, api: Api):
    alice_of(api)
    bob = alice_of(api, "Bob")
    carol = alice_of(api, "Carol")
    page.goto("/transactions/new")
    page.locator("[data-modes]").get_by_text("Split", exact=True).click()
    rows = page.locator('[data-people-editor="expense"] .share-row:visible')
    expect(rows).to_have_count(1)  # only you
    page.locator('[data-people-editor="expense"] [data-add-people]').click()
    sheet = page.locator("#people-picker")
    expect(sheet.locator("[data-people-option]")).to_have_count(3)
    sheet.locator("[data-people-search]").fill("bo")
    expect(sheet.locator("[data-people-name]:visible")).to_have_count(1)
    sheet.locator("[data-people-search]").fill("")
    sheet.locator("[data-people-option]", has_text="Alice").click()
    sheet.locator("[data-people-option]", has_text="Bob").click()
    expect(sheet.locator("[data-people-done]")).to_have_text("Done · 2 people")
    sheet.locator("[data-people-done]").click()
    expect(rows).to_have_count(3)
    expect(page.locator(f'input[name="with_{carol["id"]}"]')).not_to_be_checked()
    page.locator(f'[data-person-row]:has(input[name="with_{bob["id"]}"]) [data-person-remove]').click()
    expect(rows).to_have_count(2)
    page.locator('[data-people-editor="expense"] summary', has_text="Someone else paid").click()
    paid = page.locator('[data-people-editor="expense"] [data-for-person]:visible')
    expect(paid).to_have_count(1)  # only Alice: the one who is in the bill
