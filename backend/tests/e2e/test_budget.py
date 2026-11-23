"""The React app's Budgets page and its category sheet in a browser (ports of test_budget_page.py, and the head and month
pill comparisons step 5 left for Budgets)."""

import re
from datetime import date, timedelta

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def ready(page: Page):
    return page.get_by_test_id("ready-figure")


def category(page: Page, name: str):
    return page.locator("main").get_by_role("button", name=re.compile(f"^{name}"))


def sheet(page: Page, name: str):
    return page.get_by_role("dialog", name=name)


def assign_in_sheet(page: Page, name: str, amount: str) -> None:
    """Tap a category, type what to assign in its sheet and save."""
    category(page, name).first.click()
    box = sheet(page, name).get_by_label("Assigned this month")
    expect(box).to_be_visible()
    box.fill(amount)
    sheet(page, name).get_by_role("button", name="Save").click()
    expect(sheet(page, name)).to_have_count(0)


def test_assigning_changes_ready_to_assign_without_a_reload(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/budget")
    expect(ready(page)).to_have_text("₹5,000.00")
    assign_in_sheet(page, "Groceries", "1200")
    expect(ready(page)).to_have_text("₹3,800.00")
    category(page, "Groceries").click()
    expect(sheet(page, "Groceries").get_by_label("Assigned this month")).to_have_value("1,200.00")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling"


def test_copying_last_months_amounts(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    api.put(f"/budget/categories/{books['food']['id']}", month=LAST_MONTH.isoformat(), amount="300")
    api.put(f"/budget/categories/{books['rent']['id']}", month=LAST_MONTH.isoformat(), amount="900")
    page.goto("/budget")
    button = page.get_by_role("button", name=re.compile("^Copy last month's amounts"))
    expect(button).to_contain_text("1,200.00")
    button.click()
    expect(button).to_have_count(0)
    category(page, "Rent").click()
    expect(sheet(page, "Rent").get_by_label("Assigned this month")).to_have_value("900.00")


def test_a_card_the_budget_includes_is_in_the_sum(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    api.post(
        "/transactions/",
        postings=[leg(books["food"], "debit", "120"), leg(books["card"], "credit", "120")],
    )
    page.goto("/budget")
    page.get_by_label("How what is ready to assign is worked out").click()
    panel = page.get_by_role("region", name="How this is worked out")
    expect(panel).to_contain_text("Set aside for card bills")
    expect(panel).to_contain_text("120.00")
    assign_in_sheet(page, "Rent", "500")
    expect(ready(page)).to_have_text("₹4,500.00")
    expect(panel).to_contain_text("380.00"), "the sum stays open and follows"


def test_the_rows_have_no_notch_under_their_bars(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    api.post("/categories/", name="Dining", kind="spending")
    api.post("/categories/", name="Delivery", kind="spending")
    page.goto("/budget")
    expect(category(page, "Rent")).to_be_visible()
    assert page.locator("main").evaluate(
        "m => [...m.querySelectorAll('i')].every(i => i.parentElement.querySelectorAll('b').length === 0)"
    ), "no tick on the rows' bars"


def test_every_bar_runs_the_full_width_of_its_row(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    api.post("/categories/", name="Dining", kind="spending")
    api.post("/categories/", name="Delivery", kind="spending")
    api.put(f"/budget/categories/{books['rent']['id']}", amount="900")
    for width in (390, 1100):
        page.set_viewport_size({"width": width, "height": 800})
        page.goto("/budget")
        expect(category(page, "Rent")).to_be_visible()
        rows = page.locator("main button:has(> span[aria-hidden='true'])")
        sizes = rows.evaluate_all(
            "els => els.map(e => [Math.round(e.getBoundingClientRect().width),"
            " Math.round(e.querySelector(':scope > span[aria-hidden]').getBoundingClientRect().width)])"
        )
        assert len(sizes) >= 4, sizes  # every category is a row, Dining and Delivery included
        assert all(row == bar for row, bar in sizes), f"at {width}px: {sizes}"


def test_names_and_amounts_line_up(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    delivery = api.post("/categories/", name="Delivery", kind="spending")
    api.put(f"/budget/categories/{books['rent']['id']}", amount="900")
    api.put(f"/budget/categories/{delivery['id']}", amount="100")
    page.goto("/budget")
    expect(category(page, "Rent")).to_be_visible()
    rows = page.locator("main button:has(> span[aria-hidden='true'])")
    lefts = rows.evaluate_all("els => els.map(e => Math.round(e.firstElementChild.getBoundingClientRect().left))")
    rights = rows.evaluate_all("els => els.map(e => Math.round(e.children[1].getBoundingClientRect().right))")
    assert len(lefts) >= 2 and len(set(lefts)) == 1, lefts
    assert len(set(rights)) == 1, rights


def test_the_i_opens_the_sum_behind_ready_to_assign(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/budget")
    panel = page.get_by_role("region", name="How this is worked out")
    expect(panel).to_have_count(0)
    page.get_by_label("How what is ready to assign is worked out").click()
    expect(panel).to_contain_text("₹5,000.00")
    page.get_by_label("How what is ready to assign is worked out").click()
    expect(panel).to_have_count(0)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_save_works_on_the_first_tap_even_when_the_sheet_moves_under_the_finger(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/budget")
    category(page, "Groceries").click()
    sheet(page, "Groceries").get_by_label("Assigned this month").fill("1200")
    area = sheet(page, "Groceries").get_by_role("button", name="Save").bounding_box()
    assert area
    page.mouse.move(area["x"] + area["width"] / 2, area["y"] + area["height"] / 2)
    page.mouse.down()
    page.evaluate("document.querySelector('dialog[open]').style.transform = 'translateY(-160px)'")
    page.mouse.up()
    expect(sheet(page, "Groceries")).to_have_count(0)
    expect(ready(page)).to_have_text("₹3,800.00")


FAKE_KEYBOARD = """
const vv = new EventTarget();
Object.assign(vv, {width: innerWidth, height: innerHeight, offsetTop: 0, offsetLeft: 0, scale: 1});
Object.defineProperty(window, "visualViewport", {value: vv, configurable: true});
window.__keyboard = (px) => { vv.height = innerHeight - px; vv.dispatchEvent(new Event("resize")); };
"""


def with_keyboard(page: Page, size, keyboard):
    """A phone of `size` where a soft keyboard of `keyboard` px takes the bottom of the screen when a field has focus."""
    page.set_viewport_size(size)
    page.add_init_script(FAKE_KEYBOARD)
    page.goto("/budget")
    category(page, "Groceries").click()
    box = sheet(page, "Groceries").get_by_label("Assigned this month")
    expect(box).to_be_visible()
    box.click()
    page.evaluate(f"window.__keyboard({keyboard})")
    page.wait_for_timeout(150)
    return box


def test_save_is_above_the_keyboard_and_tappable_on_a_phone_and_a_small_phone(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    for size, keyboard in (({"width": 390, "height": 844}, 340), ({"width": 320, "height": 568}, 290)):
        box = with_keyboard(page, size, keyboard)
        box.fill("1200")
        save = sheet(page, "Groceries").get_by_role("button", name="Save")
        area = save.bounding_box()
        assert area
        visible_bottom = size["height"] - keyboard
        assert area["y"] >= 0 and area["y"] + area["height"] <= visible_bottom, f"Save under the keyboard: {area}"
        x, y = area["x"] + area["width"] / 2, area["y"] + area["height"] / 2
        assert (
            page.evaluate("([x, y]) => document.elementFromPoint(x, y).closest('button')?.textContent.trim()", [x, y])
            == "Save"
        )
        page.mouse.click(x, y)
        expect(sheet(page, "Groceries")).to_have_count(0)
        expect(ready(page)).to_have_text("₹3,800.00")
        page.evaluate("window.__keyboard(0)")
        api.put(f"/budget/categories/{books['food']['id']}", amount="0")


def test_a_tap_beside_the_sheet_while_typing_only_puts_the_keyboard_away(signed_in_page: Page, books):
    page = signed_in_page
    box = with_keyboard(page, {"width": 390, "height": 844}, 340)
    box.fill("77")
    page.mouse.click(195, 20)  # the dim area above the sheet
    expect(sheet(page, "Groceries")).to_be_visible()
    expect(box).not_to_be_focused()
    expect(box).to_have_value("77.00"), "what was typed is kept, written out with its decimals"
    page.mouse.click(195, 20)
    expect(sheet(page, "Groceries")).to_have_count(0)


def test_save_works_after_the_keyboard_is_put_away_with_its_own_button(signed_in_page: Page, books):
    page = signed_in_page
    box = with_keyboard(page, {"width": 390, "height": 844}, 340)
    box.fill("1234")
    page.evaluate("document.activeElement.blur()")  # no viewport event, as on iOS
    page.wait_for_timeout(400)
    save = sheet(page, "Groceries").get_by_role("button", name="Save")
    area = save.bounding_box()
    assert area and area["y"] + area["height"] > 844 - 340, "the sheet is back down"
    save.click()
    expect(sheet(page, "Groceries")).to_have_count(0)


def test_tapping_the_amount_in_a_sheet_focuses_it_and_does_not_close_the_sheet(
    signed_in_page: Page, books, server: str
):
    """On a phone, focusing the amount makes the sheet change shape and the release can land on the dim area, which used
    to close the sheet."""
    page = signed_in_page
    phone = page.context.browser.new_context(
        base_url=server, has_touch=True, is_mobile=True, viewport={"width": 390, "height": 780}
    )
    phone.add_cookies(page.context.cookies())
    try:
        mobile = phone.new_page()
        mobile.set_default_timeout(8000)
        mobile.goto("/budget")
        category(mobile, "Groceries").tap()
        box = sheet(mobile, "Groceries").get_by_label("Assigned this month")
        expect(box).to_be_visible()
        mobile.wait_for_timeout(700)  # the sheet has finished sliding in
        box.tap()
        mobile.wait_for_timeout(300)
        expect(sheet(mobile, "Groceries")).to_be_visible()
        expect(box).to_be_focused()
    finally:
        phone.close()


def test_the_month_pill_sits_on_the_same_line_on_home_and_the_other_pages(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    api.post(
        "/transactions/",
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
    )
    for width in (390, 1280):
        page.set_viewport_size({"width": width, "height": 800})
        tops, ends = {}, {}
        for path in ("/", "/budget", "/categories", "/transactions"):
            page.goto(path)
            pill = page.get_by_label("Choose a month").locator("xpath=../..")
            expect(pill).to_have_count(1)
            box = pill.bounding_box()
            assert box
            tops[path], ends[path] = round(box["y"]), round(box["x"] + box["width"])
        assert len(set(tops.values())) == 1, (width, tops)
        assert len({ends[p] for p in ("/budget", "/categories", "/transactions")}) == 1, (width, ends)


def test_the_head_is_the_same_on_accounts_categories_and_budgets(signed_in_page: Page, books):
    page = signed_in_page
    spots = {}
    accounts = re.compile(r"^\d+ accounts?$")
    for path, label in (("/accounts", accounts), ("/categories", "Spent so far"), ("/budget", "Ready to assign")):
        page.goto(path)
        title = page.locator("main h1").first.bounding_box()
        top = (
            page.get_by_text(label) if isinstance(label, re.Pattern) else page.get_by_text(label, exact=True)
        ).bounding_box()
        assert title and top
        spots[path] = (round(title["y"]), round(top["y"]))
    assert len({s[0] for s in spots.values()}) == 1, f"the titles line up: {spots}"
    assert spots["/accounts"][1] <= spots["/budget"][1], f"the quiet line sits under the title: {spots}"


def test_move_money_picks_in_our_sheet_with_what_each_has_left(signed_in_page: Page, api: Api, books):
    page = signed_in_page
    api.put(f"/budget/categories/{books['food']['id']}", amount="300")
    api.put(f"/budget/categories/{books['rent']['id']}", amount="50")
    page.goto("/budget/move")
    page.get_by_label("Amount").fill("120")
    page.get_by_role("button", name=re.compile("^From")).click()
    picker = page.get_by_role("dialog", name="From")
    expect(picker.get_by_role("button", name=re.compile("Groceries"))).to_contain_text("300.00 left")
    picker.get_by_role("button", name=re.compile("Groceries")).click()
    expect(page.get_by_role("button", name=re.compile("^From"))).to_have_text("Groceries")
    page.get_by_role("button", name=re.compile("^To(?! do)")).click()
    page.get_by_role("dialog", name="To").get_by_role("button", name=re.compile("Rent")).click()
    page.get_by_role("button", name="Move money").click()
    page.wait_for_url(re.compile(r"/budget\?month="))
    expect(category(page, "Rent")).to_contain_text("170.00")
    expect(category(page, "Groceries")).to_contain_text("180.00")


def test_move_money_without_both_categories_says_so(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/budget/move")
    page.get_by_label("Amount").fill("10")
    page.get_by_role("button", name="Move money").click()
    expect(page.get_by_role("alert")).to_contain_text("Choose the category")


def test_moving_from_a_category_sheet_starts_from_it(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/budget")
    category(page, "Rent").click()
    sheet(page, "Rent").get_by_role("link", name="Move money").click()
    page.wait_for_url(re.compile(r"/budget/move\?"))
    expect(page.get_by_role("button", name=re.compile("^From"))).to_have_text("Rent")
