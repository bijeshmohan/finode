"""The budget page in a browser: assigning in place, copying last month, what is ready to assign."""

import re
from datetime import date, timedelta

import pytest
from playwright.sync_api import Page, expect

from .conftest import Api

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def ready(page: Page) -> str:
    return page.locator("[data-budget-head='spend'] .figure").inner_text()


def assign_in_sheet(page: Page, name: str, amount: str) -> None:
    """Tap a category, type what to assign in its sheet and save."""
    page.locator("a.catrow", has_text=name).first.click()
    box = page.locator(f'#cat-sheet input[aria-label="Assigned to {name}"]')
    expect(box).to_be_visible()
    box.fill(amount)
    page.locator("#cat-sheet").get_by_role("button", name="Save").click()
    expect(page.locator("#cat-sheet")).not_to_be_visible()


def test_assigning_changes_ready_to_assign_without_a_reload(page: Page, books):
    page.goto("/budget")
    assert ready(page) == "\u20b95,000.00"
    assign_in_sheet(page, "Groceries", "1200")
    expect(page.locator("[data-budget-head='spend'] .figure")).to_have_text("\u20b93,800.00")
    page.locator("a.catrow", has_text="Groceries").first.click()
    assert page.locator('#cat-sheet input[aria-label="Assigned to Groceries"]').input_value() == "1,200.00"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "no sideways scrolling on a phone"
    )


def test_copying_last_months_amounts(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['food']['aid']}", month=LAST_MONTH.isoformat(), amount="300")
    api.put(f"/budget/categories/{books['rent']['aid']}", month=LAST_MONTH.isoformat(), amount="900")
    page.goto("/budget")
    page.locator("button.need-line").click()
    button = page.get_by_role("button", name="Copy last month's amounts")
    expect(button).to_contain_text("1,200.00")
    button.click()
    expect(button).to_have_count(0)
    page.locator("a.catrow", has_text="Rent").first.click()
    assert page.locator('#cat-sheet input[aria-label="Assigned to Rent"]').input_value() in ("900.00", "900")


def test_a_card_the_budget_includes_is_in_the_sum(page: Page, books, api: Api):
    api.post(
        "/transactions/",
        postings=[
            {"account": books["food"]["aid"], "side": "debit", "amount": "120"},
            {"account": books["card"]["aid"], "side": "credit", "amount": "120"},
        ],
    )
    page.goto("/budget")
    expect(page.get_by_text("credit account")).to_have_count(0)
    page.locator("[data-budget-head='spend'] .calc-info > summary").click()
    expect(page.locator(".calc-panel")).to_contain_text("Set aside for card bills")
    expect(page.locator(".calc-panel")).to_contain_text("120.00")
    # Assigning money to a category changes ready to assign, and the explanation follows it.
    assign_in_sheet(page, "Rent", "500")
    expect(page.locator("[data-budget-head='spend'] .figure")).to_have_text("\u20b94,500.00")
    expect(page.locator(".calc-panel")).to_contain_text("380.00")


def test_a_group_opens_its_page_and_its_budget_cannot_go_below_its_categories(page: Page, books, api: Api):
    dining = api.post("/accounts/", name="Dining", parent_id=books["roots"]["Expenses"])
    delivery = api.post("/accounts/", name="Delivery", parent_id=dining["aid"])
    api.post("/accounts/", name="Restaurant", parent_id=dining["aid"])
    api.put(f"/budget/categories/{delivery['aid']}", amount="300")
    page.goto("/budget")
    expect(page.locator("a.catrow", has_text="Delivery")).to_have_count(0)  # inside the group, on its page
    expect(page.locator("a.grow", has_text="Dining")).to_contain_text("Delivery")  # the hint names what is inside
    page.locator("a.grow", has_text="Dining").click()
    page.wait_for_url("**/budget/group/**")
    expect(page.locator("a.catrow", has_text="Delivery")).to_be_visible()
    page.locator(".budget-hero").click()
    box = page.locator('#cat-sheet input[aria-label="Assigned to Dining"]')
    expect(box).to_be_visible()
    box.fill("200")  # below what Delivery and Restaurant add up to
    expect(box).to_have_attribute("aria-invalid", "true")
    page.locator("#cat-sheet").get_by_role("button", name="Save").click()
    expect(page.locator("#cat-sheet")).to_be_visible()  # refused: still open
    box.fill("700")
    expect(box).to_have_attribute("aria-invalid", "false")
    page.locator("#cat-sheet").get_by_role("button", name="Save").click()
    expect(page.locator("#cat-sheet")).not_to_be_visible()
    expect(page.locator(".budget-hero .figure")).to_have_text(
        "\u20b9700.00"
    )  # the group's page block was replaced, still on the group page
    expect(page.locator("a.catrow", has_text="Delivery")).to_be_visible()
    page.get_by_role("link", name="Budgets", exact=True).first.click()
    expect(page.locator("[data-budget-head='spend'] .figure")).to_have_text("\u20b94,300.00")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_budget_rows_have_no_notch_under_their_bars(page: Page, books, api: Api):
    dining = api.post("/accounts/", name="Dining", parent_id=books["roots"]["Expenses"])
    api.post("/accounts/", name="Delivery", parent_id=dining["aid"])
    page.goto("/budget")
    expect(page.locator("a.crow .bar").first).to_be_visible()
    expect(page.locator("a.crow .pace")).to_have_count(0)


def test_every_bar_runs_the_full_width_of_its_row(page: Page, books, api: Api):
    """A bar shorter than its row reads as "partly full" even when it is complete, so it spans the whole row, at phone and desktop width."""
    dining = api.post("/accounts/", name="Dining", parent_id=books["roots"]["Expenses"])
    api.post("/accounts/", name="Delivery", parent_id=dining["aid"])
    api.put(f"/budget/categories/{books['rent']['aid']}", amount="900")
    for width in (390, 1100):
        page.set_viewport_size({"width": width, "height": 800})
        page.goto("/budget")
        sizes = page.eval_on_selector_all(
            "a.crow.has-bar",
            "els => els.map(e => [Math.round(e.getBoundingClientRect().width), Math.round(e.querySelector('.bar').getBoundingClientRect().width)])",
        )
        assert len(sizes) >= 3, sizes
        assert all(row == bar for row, bar in sizes), f"at {width}px: {sizes}"


def test_budget_names_and_amounts_line_up(page: Page, books, api: Api):
    delivery = api.post("/accounts/", name="Delivery", parent_id=books["food"]["aid"])
    api.put(f"/budget/categories/{books['rent']['aid']}", amount="900")
    api.put(f"/budget/categories/{delivery['aid']}", amount="100")
    page.goto("/budget")
    lefts = page.eval_on_selector_all(
        ".crow-name", "els => els.filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().left))"
    )
    rights = page.eval_on_selector_all(
        ".crow-amt", "els => els.filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().right))"
    )
    assert len(lefts) >= 2 and len(set(lefts)) == 1, lefts
    assert len(set(rights)) == 1, rights


def test_the_i_opens_the_sum_behind_ready_to_assign_and_survives_assigning(page: Page, books):
    page.goto("/budget")
    panel = page.locator(".budget-head .calc-panel")
    expect(panel).not_to_be_visible()
    page.get_by_label("How what is ready to assign is worked out").click()
    expect(panel).to_be_visible()
    expect(panel.locator(".total")).to_contain_text("₹5,000.00")
    page.get_by_label("How what is ready to assign is worked out").click()
    expect(panel).not_to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "no sideways scrolling on a phone"
    )


def test_save_works_on_the_first_tap_even_when_the_sheet_moves_under_the_finger(page: Page, books):
    """The keyboard opening or closing shifts a bottom sheet while a tap is under way; the click then goes to whatever is
    under the finger at the end, and Save used to need another tap."""
    page.goto("/budget")
    page.locator("a.catrow", has_text="Groceries").first.click()
    box = page.locator('#cat-sheet input[aria-label="Assigned to Groceries"]')
    box.fill("1200")
    area = page.locator("#cat-sheet").get_by_role("button", name="Save").bounding_box()
    page.mouse.move(area["x"] + area["width"] / 2, area["y"] + area["height"] / 2)
    page.mouse.down()
    page.evaluate("document.querySelector('#cat-sheet').style.transform = 'translateY(-160px)'")  # the sheet moves away
    page.mouse.up()
    expect(page.locator("#cat-sheet")).not_to_be_visible()
    expect(page.locator("[data-budget-head='spend'] .figure")).to_have_text("₹3,800.00")  # 5,000 - 1,200: it saved


FAKE_KEYBOARD = """
const vv = new EventTarget();
Object.assign(vv, {width: innerWidth, height: innerHeight, offsetTop: 0, offsetLeft: 0, scale: 1});
Object.defineProperty(window, "visualViewport", {value: vv, configurable: true});
window.__keyboard = (px) => { vv.height = innerHeight - px; vv.dispatchEvent(new Event("resize")); };
"""


def with_keyboard(page: Page, books, size, keyboard):
    """A phone of `size` where a soft keyboard of `keyboard` px takes the bottom of the screen when a field has focus."""
    page.set_viewport_size(size)
    page.add_init_script(FAKE_KEYBOARD)
    page.goto("/budget")
    page.locator("a.catrow", has_text="Groceries").first.click()
    box = page.locator('#cat-sheet input[aria-label="Assigned to Groceries"]')
    expect(box).to_be_visible()
    box.click()
    page.evaluate(f"window.__keyboard({keyboard})")
    page.wait_for_timeout(150)
    return box


def test_save_is_above_the_keyboard_and_tappable_on_a_phone_and_a_small_phone(page: Page, books):
    for size, keyboard in (({"width": 390, "height": 844}, 340), ({"width": 320, "height": 568}, 290)):
        box = with_keyboard(page, books, size, keyboard)
        box.fill("1200")
        save = page.locator("#cat-sheet").get_by_role("button", name="Save")
        area = save.bounding_box()
        visible_bottom = size["height"] - keyboard
        assert area["y"] >= 0 and area["y"] + area["height"] <= visible_bottom, (
            f"Save is under the keyboard on {size}: {area}"
        )
        x, y = area["x"] + area["width"] / 2, area["y"] + area["height"] / 2
        assert (
            page.evaluate("([x, y]) => document.elementFromPoint(x, y).closest('button')?.textContent.trim()", [x, y])
            == "Save"
        )
        page.mouse.click(x, y)
        expect(page.locator("#cat-sheet")).not_to_be_visible()
        expect(page.locator("[data-budget-head='spend'] .figure")).to_have_text(
            "₹3,800.00"
        )  # it saved on the first tap
        page.evaluate("window.__keyboard(0)")
        api_reset = page.request.put(f"/api/budget/categories/{books['food']['aid']}", data={"amount": "0"})
        assert api_reset.ok


def test_a_tap_beside_the_sheet_while_typing_only_puts_the_keyboard_away(page: Page, books):
    box = with_keyboard(page, books, {"width": 390, "height": 844}, 340)
    box.fill("77")
    page.mouse.click(195, 20)  # the dim area above the sheet
    expect(page.locator("#cat-sheet")).to_be_visible()
    expect(box).not_to_be_focused()
    assert box.input_value() == "77.00", "what was typed is kept, written out with its decimals"
    page.mouse.click(195, 20)
    expect(page.locator("#cat-sheet")).not_to_be_visible()


def test_save_works_after_the_keyboard_is_put_away_with_its_own_button(page: Page, books):
    """iOS's tick under the keyboard blurs the field and closes the keyboard without a resize event; Save must still work."""
    box = with_keyboard(page, books, {"width": 390, "height": 844}, 340)
    box.fill("1234")
    page.evaluate("document.activeElement.blur()")  # the viewport is left as it was: no event, like iOS
    page.wait_for_timeout(200)
    save = page.locator("#cat-sheet").get_by_role("button", name="Save")
    area = save.bounding_box()
    assert area["y"] + area["height"] > 844 - 340, "the sheet is back down, not lifted over the empty space"
    x, y = area["x"] + area["width"] / 2, area["y"] + area["height"] / 2
    assert (
        page.evaluate("([x, y]) => document.elementFromPoint(x, y).closest('button')?.textContent.trim()", [x, y])
        == "Save"
    )
    save.click()
    expect(page.locator("#cat-sheet")).not_to_be_visible()
    assert page.request.get("/api/budget/").ok
    page.evaluate("window.__keyboard(0)")
    page.request.put(f"/api/budget/categories/{books['food']['aid']}", data={"amount": "0"})


def test_a_new_goal_is_made_from_the_save_chip_and_shows_its_share_as_you_type(page: Page, books):
    index = THIS_MONTH.year * 12 + THIS_MONTH.month - 1 + 5
    by = f"{index // 12}-{index % 12 + 1:02d}"
    page.goto("/budget")
    expect(page.locator(".cat-chips .chip[aria-pressed='true']")).to_have_text("Spend")
    page.locator(".cat-chips .chip", has_text="Save").click()
    page.wait_for_url(re.compile(r"tab=save"))
    page.get_by_role("link", name="New goal").click()
    page.wait_for_url(re.compile(r"/budget/goal$"))
    expect(page.locator("#goal-calc")).to_contain_text("—")
    page.locator('input[name="name"]').fill("Goa trip")
    page.locator('input[name="amount"]').fill("1,00,000")
    page.locator('input[name="by"]').fill(by)
    expect(page.locator("#goal-calc")).to_contain_text("16,666.67 a month")
    expect(page.locator("#goal-calc")).to_contain_text("6 months")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        "no sideways scrolling on a phone"
    )
    page.get_by_role("button", name="Create goal").click()
    page.wait_for_url(re.compile(r"/budget\?tab=save$"))
    row = page.locator("a.goalrow", has_text="Goa trip")
    expect(row).to_be_visible()
    expect(row).to_contain_text("16,666.67")
    expect(row).to_contain_text("This month done")
    expect(page.locator(".toast")).to_contain_text("Goal created")
    expect(page.locator("[data-budget-head='save']")).to_contain_text("16,666.67")


def test_a_goals_sheet_sets_money_aside_and_deletes_the_goal(page: Page, books, api: Api):
    index = THIS_MONTH.year * 12 + THIS_MONTH.month - 1 + 5
    page.request.post(
        "/budget/goal", form={"name": "Bike", "amount": "60000", "by": f"{index // 12}-{index % 12 + 1:02d}"}
    )
    page.goto("/budget?tab=save")
    expect(page.locator("a.goalrow", has_text="Bike")).to_contain_text("10,000.00 to go this month")
    page.locator("a.goalrow", has_text="Bike").click()
    sheet = page.locator("#cat-sheet")
    expect(sheet).to_be_visible()
    sheet.get_by_role("button", name=re.compile(r"Set aside .*10,000.00 this month")).click()
    expect(sheet).not_to_be_visible()
    expect(page.locator("a.goalrow", has_text="Bike")).to_contain_text("This month done")
    expect(page.locator(".cat-chips .chip[aria-pressed='true']")).to_have_text("Save")
    page.locator("a.goalrow", has_text="Bike").click()
    page.on("dialog", lambda d: d.accept())
    sheet.get_by_role("button", name="Delete goal").click()
    page.wait_for_url(re.compile(r"/budget\?tab=save$"))
    expect(page.locator("a.goalrow")).to_have_count(0)
    expect(page.locator(".toast")).to_contain_text("Goal deleted")


def test_a_goal_hands_its_money_to_a_category_from_its_sheet(page: Page, books, api: Api):
    index = THIS_MONTH.year * 12 + THIS_MONTH.month - 1 + 5
    page.request.post(
        "/budget/goal",
        form={"name": "Bike", "amount": "60000", "by": f"{index // 12}-{index % 12 + 1:02d}", "assign_now": "1"},
    )
    page.goto("/budget?tab=save")
    page.locator("a.goalrow", has_text="Bike").click()
    sheet = page.locator("#cat-sheet")
    expect(sheet).to_be_visible()
    sheet.get_by_role("button", name="Use it for…").click()
    expect(sheet.locator("h2")).to_have_text("Use Bike for…")
    sheet.locator("select[name=category]").select_option(books["rent"]["aid"])
    sheet.locator("input[name=amount]").fill("4,000")
    sheet.get_by_role("button", name="Use it").click()
    expect(sheet).not_to_be_visible()
    expect(page.locator("a.goalrow", has_text="Bike")).to_contain_text("6,000.00")
    expect(page.locator(".cat-chips .chip[aria-pressed='true']")).to_have_text("Save")
    page.locator(".cat-chips .chip", has_text="Spend").click()
    expect(page.locator(".crow", has_text="Rent")).to_contain_text("4,000.00")


@pytest.mark.parametrize("width", [390, 1280])
def test_the_month_pill_sits_on_the_same_line_on_home_and_the_other_pages(page: Page, books, api: Api, width):
    api.post(
        "/transactions/",
        postings=[
            {"account": books["food"]["aid"], "side": "debit", "amount": "40"},
            {"account": books["checking"]["aid"], "side": "credit", "amount": "40"},
        ],
    )
    page.set_viewport_size({"width": width, "height": 800})
    tops = {}
    for name, path in (
        ("home", "/"),
        ("budget", "/budget"),
        ("categories", "/categories"),
        ("transactions", "/transactions"),
    ):
        page.goto(path)
        assert page.locator(".month-pill").count() == 1, f"no month pill on {name}"
        tops[name] = page.locator(".month-pill").bounding_box()["y"]
    assert len({round(t) for t in tops.values()}) == 1, tops


def test_tapping_the_amount_in_a_sheet_focuses_it_and_does_not_close_the_sheet(
    page: Page, books, api: Api, live_server: str
):
    """On a phone, focusing the amount makes the sheet change shape and the release can land on the dim area, which used to
    close the sheet (a subcategory on a group's page lost the tap far more often than a top-level category)."""
    dining = api.post("/accounts/", name="Dining", parent_id=books["roots"]["Expenses"])
    api.post("/accounts/", name="Delivery", parent_id=dining["aid"])
    phone = page.context.browser.new_context(
        base_url=live_server, has_touch=True, is_mobile=True, viewport={"width": 390, "height": 780}
    )
    try:
        mobile = phone.new_page()
        mobile.set_default_timeout(8000)

        def tap_amount(label: str):
            box = mobile.locator(f'#cat-sheet input[aria-label="Assigned to {label}"]')
            expect(box).to_be_visible()
            mobile.wait_for_timeout(700)  # the sheet has finished sliding in
            box.tap()
            mobile.wait_for_timeout(300)
            expect(mobile.locator("#cat-sheet")).to_be_visible()
            expect(box).to_be_focused()

        mobile.goto("/budget")
        mobile.locator("a.catrow", has_text="Groceries").first.tap()
        tap_amount("Groceries")
        mobile.goto("/budget")
        mobile.locator("a.grow", has_text="Dining").tap()
        mobile.wait_for_url("**/budget/group/**")
        mobile.locator("a.catrow", has_text="Delivery").tap()
        tap_amount("Delivery")
    finally:
        phone.close()


def test_home_is_centred_beside_the_sidebar_and_its_day_label_lines_up(page: Page, books, api: Api):
    api.post(
        "/transactions/",
        postings=[
            {"account": books["food"]["aid"], "side": "debit", "amount": "40"},
            {"account": books["checking"]["aid"], "side": "credit", "amount": "40"},
        ],
    )
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto("/")
    column = page.evaluate("""() => {
      const main = document.querySelector('main').getBoundingClientRect();
      const side = document.querySelector('.sidebar').getBoundingClientRect();
      return [main.left - side.right, innerWidth - main.right];
    }""")
    assert abs(column[0] - column[1]) <= 2, f"equal space on both sides of the column: {column}"
    heading = page.locator(".home-recent .section-head h2").bounding_box()["x"]
    day = page.locator(".tx-day-head").first.bounding_box()["x"]
    assert abs(heading - day) <= 1, "the day label starts where the heading does"
