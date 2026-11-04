"""Choosing an account in a sheet on the Add screen: grouped by name, with balances, searchable, the other side's account
greyed, and a new account made from it."""

from playwright.sync_api import Page, expect

from .conftest import Api


def test_an_account_is_chosen_in_a_sheet(page: Page, books, api: Api):
    page.goto("/transactions/new")
    button = page.locator('[data-rows="credit"] [data-pick]:visible')
    expect(button).to_have_text("Account…")
    button.click()
    dialog = page.locator("#row-picker")
    expect(dialog).to_be_visible()
    expect(dialog.locator(".filter-title")).to_have_text("Account")
    checking = dialog.locator("[data-pick-option]", has_text="Checking")
    expect(checking.locator(".pick-balance")).to_have_text("5,000.00")
    expect(dialog.locator("[data-pick-option]", has_text="Visa").locator(".pick-balance")).to_have_text("owed 0.00")
    dialog.locator("[data-pick-search]").fill("chec")
    expect(dialog.locator("[data-pick-option]")).to_have_count(1)
    checking.click()
    expect(dialog).to_be_hidden()  # one tap chooses: the amount and date are set from the row afterwards
    expect(button).to_have_text("Checking")
    assert page.input_value('[data-rows="credit"] select') == books["checking"]["id"]
    page.fill("#total", "40")
    page.locator('[data-rows="debit"] [data-pick]:visible').click()
    page.locator("#row-picker [data-pick-option]", has_text="Groceries").click()
    page.get_by_role("button", name="Save", exact=True).click()
    page.wait_for_url("**/transactions")
    [entry] = api.get("/transactions/")[:1]
    assert {p["category_id"] or p["account_id"] for p in entry["postings"]} == {
        books["checking"]["id"],
        books["food"]["id"],
    }


def test_the_account_on_the_other_side_is_greyed(page: Page, books):
    page.goto("/transactions/new")
    page.get_by_role("button", name="Transfer", exact=True).click()
    page.locator('[data-rows="credit"] [data-pick]:visible').click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").click()
    page.locator('[data-rows="debit"] [data-pick]:visible').click()
    expect(page.locator("#row-picker [data-pick-option]", has_text="Checking")).to_be_disabled()
    expect(page.locator("#row-picker [data-pick-option]", has_text="Cash")).to_be_enabled()


def test_a_new_account_can_be_made_from_the_sheet(page: Page, books, api: Api):
    page.goto("/transactions/new")
    button = page.locator('[data-rows="credit"] [data-pick]:visible')
    button.click()
    page.locator("#row-picker [data-pick-new]").click()
    dialog = page.locator("#quick-account")
    expect(dialog).to_be_visible()
    dialog.locator('input[name="name"]').fill("Kotak")
    dialog.get_by_role("button", name="Add account").click()
    expect(dialog).not_to_be_visible()
    expect(button).to_have_text("Kotak")
    assert any(a["name"] == "Kotak" for a in api.get("/accounts/"))


def test_the_chosen_account_is_bold_and_the_scroll_bar_stays_clear_of_the_balances(page: Page, books, api: Api):
    for number in range(25):
        api.post("/accounts/", name=f"Wallet {number:02d}", parent_id=books["roots"]["Assets"], balance="1500")
    page.goto("/transactions/new")
    page.locator('[data-rows="credit"] [data-pick]:visible').click()
    page.locator("#row-picker [data-pick-option]", has_text="Checking").click()
    page.locator('[data-rows="credit"] [data-pick]:visible').click()
    assert page.locator("#row-picker .tag-tick").count() == 0, "no tick circle on the options themselves"
    chosen = page.locator('#row-picker [aria-pressed="true"] > span:first-child').first
    assert chosen.evaluate("el => getComputedStyle(el).fontWeight") == "600"
    list_box = page.locator("#row-picker [data-pick-list]")
    assert list_box.evaluate("el => el.scrollHeight > el.clientHeight"), "the list is long enough to scroll"
    edge = list_box.bounding_box()["x"] + list_box.evaluate("el => el.clientWidth")  # where a scroll bar begins
    balance = page.locator("#row-picker .pick-balance").first.bounding_box()
    assert balance["x"] + balance["width"] <= edge, "the figures end before the scroll bar"


def test_chips_and_search_results_show_the_name_and_the_group_under_it_without_an_arrow(page: Page, books, api: Api):
    banks = api.post("/accounts/", name="Banks", parent_id=books["roots"]["Assets"])
    api.post("/accounts/", name="Kotak", parent_id=banks["id"])
    food = api.post("/accounts/", name="Food", parent_id=books["roots"]["Expenses"])
    api.post("/accounts/", name="Dining", parent_id=food["id"])
    page.goto("/transactions/new")
    account = page.locator('[data-rows="credit"] [data-pick]:visible')
    account.click()
    page.locator("#row-picker [data-pick-option]", has_text="Kotak").first.click()
    expect(account).to_have_text("Kotak")
    category = page.locator('[data-rows="debit"] [data-pick]:visible')
    category.click()
    page.locator("#row-picker [data-pick-option]", has_text="Dining").first.click()
    expect(category).to_have_text("Dining")
    account.click()
    page.locator("#row-picker [data-pick-search]").fill("kot")
    found = page.locator("#row-picker [data-pick-option]")
    expect(found).to_contain_text("Kotak")
    expect(found).to_contain_text("Banks")  # a match outside its heading names its group under it
    assert "›" not in page.locator("#row-picker").inner_text()
    page.evaluate("document.getElementById('row-picker').close()")
    category.click()
    assert "›" not in page.locator("#row-picker").inner_text()


def test_pressing_an_option_keeps_the_search_focused_so_the_sheet_does_not_move(page: Page, books):
    """On a phone, a press that takes focus off the search puts the keyboard away and the sheet drops under the finger: the
    tap then lands elsewhere and nothing is chosen."""
    page.goto("/transactions/new")
    page.locator('[data-rows="credit"] [data-pick]:visible').click()
    dialog = page.locator("#row-picker")
    search = dialog.locator("[data-pick-search]")
    search.fill("chec")
    search.focus()
    box = dialog.locator("[data-pick-option]", has_text="Checking").bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    expect(search).to_be_focused()
    page.mouse.up()
    expect(dialog).to_be_hidden()  # chosen at once


IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"


def test_on_an_iphone_the_sheet_keeps_room_for_the_keyboards_form_bar(browser, live_server, books):
    """Safari on iOS draws a translucent bar over the bottom of the page, above the keyboard, which the visual viewport does
    not count: a single filtered row sat under it. While the search has focus the sheet keeps room below its content."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        base_url=live_server,
        reduced_motion="reduce",
        has_touch=True,
        is_mobile=True,
        user_agent=IPHONE,
    )
    page = context.new_page()
    page.set_default_timeout(8000)
    page.goto("/transactions/new")
    page.locator('[data-rows="credit"] [data-pick]:visible').click()
    dialog = page.locator("#row-picker")
    search = dialog.locator("[data-pick-search]")
    search.focus()
    search.fill("chec")
    room = dialog.evaluate("el => parseFloat(getComputedStyle(el).paddingBottom)")
    assert room >= 40
    search.blur()
    page.wait_for_timeout(800)
    assert dialog.evaluate("el => parseFloat(getComputedStyle(el).paddingBottom)") < 40
    context.close()


def test_off_an_iphone_the_sheet_keeps_no_extra_room(page: Page, books):
    page.goto("/transactions/new")
    page.locator('[data-rows="credit"] [data-pick]:visible').click()
    dialog = page.locator("#row-picker")
    dialog.locator("[data-pick-search]").focus()
    assert dialog.evaluate("el => parseFloat(getComputedStyle(el).paddingBottom)") < 40
