"""The budget page in a browser: assigning in place, copying last month, what is ready to assign."""

import re
from datetime import date, timedelta

from playwright.sync_api import Page, expect

from .conftest import Api

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def ready(page: Page) -> str:
    return page.locator(".ready-hero .figure").inner_text()


def assign_in_sheet(page: Page, name: str, amount: str) -> None:
    """Tap a category, type what to assign in its sheet and save."""
    page.locator("a.catrow", has_text=name).first.click()
    box = page.locator(f'#cat-sheet input[aria-label="Assigned to {name}"]')
    expect(box).to_be_visible()
    box.fill(amount)
    page.locator("#cat-sheet").get_by_role("button", name="Save").click()
    expect(page.locator("#cat-sheet")).not_to_be_visible()


def test_assigning_changes_ready_to_assign_without_a_reload(page: Page, books):
    page.goto("/plan")
    assert ready(page) == "\u20b95,000.00"
    assign_in_sheet(page, "Groceries", "1200")
    expect(page.locator(".ready-hero .figure")).to_have_text("\u20b93,800.00")
    page.locator("a.catrow", has_text="Groceries").first.click()
    assert page.locator('#cat-sheet input[aria-label="Assigned to Groceries"]').input_value() == "1,200.00"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone"


def test_copying_last_months_amounts(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['food']['aid']}", month=LAST_MONTH.isoformat(), amount="300")
    api.put(f"/budget/categories/{books['rent']['aid']}", month=LAST_MONTH.isoformat(), amount="900")
    page.goto("/plan")
    page.locator("button.need").click()
    button = page.get_by_role("button", name="Copy last month's amounts")
    expect(button).to_contain_text("1,200.00")
    button.click()
    expect(button).to_have_count(0)
    page.locator("a.catrow", has_text="Rent").first.click()
    assert page.locator('#cat-sheet input[aria-label="Assigned to Rent"]').input_value() in ("900.00", "900")


def test_a_target_shows_what_is_missing_and_funding_fills_it(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['rent']['aid']}/target", kind="monthly", amount="800")
    page.goto("/plan")
    expect(page.locator("a.catrow .crow-sub.short")).to_contain_text("needs 800.00 more")
    page.locator("button.need").click()
    page.get_by_role("button", name="Assign what is needed").click()
    expect(page.locator("a.catrow .crow-sub.short")).to_have_count(0)
    expect(page.locator(".ready-hero .figure")).to_have_text("\u20b94,200.00")


def test_a_card_the_budget_includes_is_listed_and_the_sum_is_explained(page: Page, books, api: Api):
    api.post("/transactions/", postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "120"},
        {"account": books["card"]["aid"], "side": "credit", "amount": "120"},
    ])
    page.goto("/")
    row = page.locator("details.home-credit")
    expect(row.locator("summary")).to_contain_text("1 credit account")
    expect(row.locator("summary")).to_contain_text("120.00 owed")
    expect(row.locator(".up-list")).to_be_hidden()  # folded until tapped
    row.locator("summary").click()
    expect(row.locator(".up-list")).to_contain_text("Visa")
    expect(row.locator(".up-list")).to_contain_text("120.00")
    page.goto("/plan")
    expect(page.get_by_text("credit account")).to_have_count(0)
    page.locator("details.how > summary").click()
    expect(page.locator(".calc").first).to_contain_text("set aside for card bills 120.00")
    # Assigning money to a category changes ready to assign, and the explanation follows it.
    assign_in_sheet(page, "Rent", "500")
    expect(page.locator(".ready-hero .figure")).to_have_text("\u20b94,500.00")
    expect(page.locator(".calc").first).to_contain_text("in categories 380.00")


def test_the_target_form_shows_the_fields_each_kind_needs(page: Page, books):
    page.goto(f"/plan/target?category={books['rent']['aid']}")
    day, month = page.locator("label[data-target-weekday]"), page.locator("label[data-target-date]")
    expect(day).to_be_hidden()
    expect(month).to_be_hidden()
    page.locator("select[data-target-kind]").select_option("weekly")
    expect(day).to_be_visible()
    expect(month).to_be_hidden()
    page.locator("select[data-target-kind]").select_option("yearly")
    expect(day).to_be_hidden()
    expect(month).to_be_visible()
    expect(month).to_contain_text("Due in")
    page.locator("select[data-target-kind]").select_option("by_date")
    expect(month).to_contain_text("By (month)")


def test_a_weekly_target_is_saved_from_the_form(page: Page, books):
    page.goto(f"/plan/target?category={books['rent']['aid']}")
    page.locator("select[data-target-kind]").select_option("weekly")
    page.locator("select[name=weekday]").select_option("4")
    page.locator("input[name=amount]").fill("100")
    page.get_by_role("button", name="Save target").click()
    page.locator("a.catrow", has_text="Rent").first.click()
    expect(page.locator("#cat-sheet")).to_contain_text("Weekly 100.00 on Fris")


def test_locking_the_books_from_settings_stops_an_edit(page: Page, books, api: Api):
    entry = api.post("/transactions/", date=str(THIS_MONTH - timedelta(days=5)), postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "40"},
        {"account": books["checking"]["aid"], "side": "credit", "amount": "40"},
    ])
    page.goto("/settings/advanced")
    page.locator("#lock summary").click()
    page.fill('input[name="locked_through"]', str(THIS_MONTH - timedelta(days=1)))
    page.get_by_role("button", name="Save lock").click()
    expect(page.locator("#lock .setting-value")).to_have_text((THIS_MONTH - timedelta(days=1)).strftime("up to %d %b %Y"))
    page.goto(f"/transactions/{entry['tid']}/edit")
    expect(page.get_by_text("This entry is in a locked period")).to_be_visible()
    expect(page.get_by_role("button", name="Save changes")).to_be_disabled()
    expect(page.get_by_role("button", name="Delete transaction")).to_be_disabled()


def test_a_weekly_target_opens_into_its_weeks(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['food']['aid']}/target", kind="weekly", amount="100", weekday=THIS_MONTH.weekday())
    api.post("/transactions/", date=str(THIS_MONTH), postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "130"},
        {"account": books["checking"]["aid"], "side": "credit", "amount": "130"},
    ])
    page.goto("/plan")
    page.locator("a.catrow", has_text="Groceries").first.click()
    weeks = page.locator("#cat-sheet details.weeks")
    expect(weeks.locator("li").first).to_contain_text("130.00 of 100.00")
    expect(weeks.locator("li.over")).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone"


def test_a_group_opens_its_page_and_its_budget_cannot_go_below_its_categories(page: Page, books, api: Api):
    dining = api.post("/accounts/", name="Dining", parent_id=books["roots"]["Expenses"])
    delivery = api.post("/accounts/", name="Delivery", parent_id=dining["aid"])
    api.post("/accounts/", name="Restaurant", parent_id=dining["aid"])
    api.put(f"/budget/categories/{delivery['aid']}", amount="300")
    page.goto("/plan")
    expect(page.locator("a.catrow", has_text="Delivery")).to_have_count(0)  # inside the group, on its page
    expect(page.locator("a.grow", has_text="Dining")).to_contain_text("Delivery")  # the hint names what is inside
    page.locator("a.grow", has_text="Dining").click()
    page.wait_for_url("**/plan/group/**")
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
    expect(page.locator(".budget-hero .figure")).to_have_text("\u20b9700.00")  # the group's page block was replaced, still on the group page
    expect(page.locator("a.catrow", has_text="Delivery")).to_be_visible()
    page.get_by_role("link", name="Plan", exact=True).first.click()
    expect(page.locator(".ready-hero .figure")).to_have_text("\u20b94,300.00")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_month_tick_on_a_budget_bar_is_a_vertical_line_not_a_clipped_dot(page: Page, books):
    page.goto("/plan")
    tick = page.locator("a.catrow .pace").first
    expect(tick).to_be_visible()
    box = tick.bounding_box()
    assert box["height"] >= 10 and box["width"] <= 4, f"a tall thin line, not a dot: {box}"
    bar = page.locator("a.catrow .bar").first
    assert bar.evaluate("e => getComputedStyle(e).overflow") == "visible", "the bar must not clip the tick"


def test_the_month_tick_also_shows_in_full_on_a_group_row(page: Page, books, api: Api):
    dining = api.post("/accounts/", name="Dining", parent_id=books["roots"]["Expenses"])
    api.post("/accounts/", name="Delivery", parent_id=dining["aid"])
    api.post("/accounts/", name="Restaurant", parent_id=dining["aid"])
    page.goto("/plan")
    tick = page.locator("a.grow .pace").first
    expect(tick).to_be_visible()
    box = tick.bounding_box()
    assert box["height"] >= 10 and box["width"] <= 4, f"a tall thin line on a group's bar too: {box}"
    bar = page.locator("a.grow .bar").first
    assert bar.evaluate("e => getComputedStyle(e).overflow") == "visible"


def test_budget_names_and_amounts_line_up(page: Page, books, api: Api):
    delivery = api.post("/accounts/", name="Delivery", parent_id=books["food"]["aid"])
    api.put(f"/budget/categories/{books['rent']['aid']}", amount="900")
    api.put(f"/budget/categories/{delivery['aid']}", amount="100")
    page.goto("/plan")
    lefts = page.eval_on_selector_all(".crow-name", "els => els.filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().left))")
    rights = page.eval_on_selector_all(".crow-amt", "els => els.filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().right))")
    assert len(lefts) >= 2 and len(set(lefts)) == 1, lefts
    assert len(set(rights)) == 1, rights



def test_the_i_opens_the_sum_behind_ready_to_assign_and_survives_assigning(page: Page, books):
    page.goto("/plan")
    panel = page.locator(".ready-hero .calc-panel")
    expect(panel).not_to_be_visible()
    page.get_by_label("How what is ready to assign is worked out").click()
    expect(panel).to_be_visible()
    expect(panel.locator(".total")).to_contain_text("₹5,000.00")
    page.get_by_label("How what is ready to assign is worked out").click()
    expect(panel).not_to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone"


def test_save_works_on_the_first_tap_even_when_the_sheet_moves_under_the_finger(page: Page, books):
    """The keyboard opening or closing shifts a bottom sheet while a tap is under way; the click then goes to whatever is
    under the finger at the end, and Save used to need another tap."""
    page.goto("/plan")
    page.locator("a.catrow", has_text="Groceries").first.click()
    box = page.locator('#cat-sheet input[aria-label="Assigned to Groceries"]')
    box.fill("1200")
    area = page.locator("#cat-sheet").get_by_role("button", name="Save").bounding_box()
    page.mouse.move(area["x"] + area["width"] / 2, area["y"] + area["height"] / 2)
    page.mouse.down()
    page.evaluate("document.querySelector('#cat-sheet').style.transform = 'translateY(-160px)'")  # the sheet moves away
    page.mouse.up()
    expect(page.locator("#cat-sheet")).not_to_be_visible()
    expect(page.locator(".ready-hero .figure")).to_have_text("₹3,800.00")  # 5,000 - 1,200: it saved


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
    page.goto("/plan")
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
        assert 0 <= area["y"] and area["y"] + area["height"] <= visible_bottom, f"Save is under the keyboard on {size}: {area}"
        x, y = area["x"] + area["width"] / 2, area["y"] + area["height"] / 2
        assert page.evaluate("([x, y]) => document.elementFromPoint(x, y).closest('button')?.textContent.trim()", [x, y]) == "Save"
        page.mouse.click(x, y)
        expect(page.locator("#cat-sheet")).not_to_be_visible()
        expect(page.locator(".ready-hero .figure")).to_have_text("₹3,800.00")  # it saved on the first tap
        page.evaluate("window.__keyboard(0)")
        api_reset = page.request.put(f"/api/budget/categories/{books['food']['aid']}", data={"amount": "0"})
        assert api_reset.ok


def test_a_tap_beside_the_sheet_while_typing_only_puts_the_keyboard_away(page: Page, books):
    box = with_keyboard(page, books, {"width": 390, "height": 844}, 340)
    box.fill("77")
    page.mouse.click(195, 20)  # the dim area above the sheet
    expect(page.locator("#cat-sheet")).to_be_visible()
    expect(box).not_to_be_focused()
    assert box.input_value() == "77", "what was typed is kept"
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
    assert page.evaluate("([x, y]) => document.elementFromPoint(x, y).closest('button')?.textContent.trim()", [x, y]) == "Save"
    save.click()
    expect(page.locator("#cat-sheet")).not_to_be_visible()
    assert page.request.get("/api/budget/").ok
    page.evaluate("window.__keyboard(0)")
    page.request.put(f"/api/budget/categories/{books['food']['aid']}", data={"amount": "0"})


def test_the_save_chip_plans_for_an_account_you_save_into(page: Page, books, api: Api):
    fund = api.post("/accounts/", name="Mutual Funds", parent_id=books["roots"]["Assets"], on_budget=False, saving=True)
    page.goto("/plan")
    chips = page.locator(".cat-chips .chip")
    expect(chips).to_have_text(["Spend", "Build", "Earn"])
    expect(page.locator(".cat-chips .chip[aria-pressed='true']")).to_have_text("Spend")
    expect(page.locator("a.catrow", has_text="Mutual Funds")).to_have_count(0)
    page.locator(".cat-chips .chip", has_text="Build").click()
    page.wait_for_url(re.compile(r"tab=build"))
    row = page.locator("[data-budget-saving] a.catrow", has_text="Mutual Funds")
    expect(row).to_be_visible()
    row.click()
    box = page.locator('#cat-sheet input[aria-label="Assigned to Mutual Funds"]')
    expect(box).to_be_visible()
    box.fill("1500")
    page.locator("#cat-sheet").get_by_role("button", name="Save").click()
    expect(page.locator("#cat-sheet")).not_to_be_visible()
    assert ready(page) == "₹3,500.00", "assigned: taken out of what is ready"
    expect(page.locator("[data-budget-saving]")).to_be_visible()  # still on Build after the swap
    expect(page.locator("[data-budget-tree]")).to_have_count(0)
    api.post("/transactions/", postings=[
        {"account": fund["aid"], "side": "debit", "amount": "1500"},
        {"account": books["checking"]["aid"], "side": "credit", "amount": "1500"}])
    page.reload()
    assert ready(page) == "₹3,500.00", "moving it in does the job and changes nothing else"


def test_the_earn_chip_plans_expected_income(page: Page, books, api: Api):
    page.goto("/plan")
    expect(page.locator(".cat-chips .chip")).to_have_text(["Spend", "Build", "Earn"])
    page.locator(".cat-chips .chip", has_text="Earn").click()
    page.wait_for_url(re.compile(r"tab=earn"))
    expect(page.locator("[data-plan-sum]")).to_be_visible()
    row = page.locator("[data-budget-earning] a.earnrow", has_text="Salary")
    expect(row).to_be_visible()
    ready_before = ready(page)
    row.click()
    box = page.locator('#cat-sheet input[aria-label="Expected from Salary"]')
    expect(box).to_be_visible()
    box.fill("85000")
    page.locator("#cat-sheet").get_by_role("button", name="Save").click()
    expect(page.locator("#cat-sheet")).not_to_be_visible()
    expect(page.locator("[data-budget-earning]")).to_be_visible()  # still on Earn after the swap
    expect(page.locator("[data-plan-sum]")).to_contain_text("85,000")
    assert ready(page) == ready_before, "expected income is not money you have"
    api.post("/transactions/", postings=[
        {"account": books["checking"]["aid"], "side": "debit", "amount": "85000"},
        {"account": books["salary"]["aid"], "side": "credit", "amount": "85000"}])
    page.reload()
    assert ready(page) != ready_before, "it arrived: now it can be assigned"
    expect(page.locator("[data-budget-earning] a.earnrow", has_text="Salary")).to_contain_text("received 85,000.00")


def test_the_sliders_button_chooses_the_sections_and_lines_up_the_rows(page: Page, books, api: Api):
    api.post("/accounts/", name="Mutual Funds", parent_id=books["roots"]["Assets"], on_budget=False, saving=True)
    page.goto("/plan")
    bar = page.locator(".cat-bar").bounding_box()
    page.goto("/categories")
    assert abs(bar["height"] - page.locator(".cat-bar").bounding_box()["height"]) < 1, "the chips row is as tall as Categories'"
    page.goto("/plan")
    page.get_by_role("link", name="Choose what to plan").click()
    sheet = page.locator("#plan-sheet")
    expect(sheet).to_be_visible()
    assert not page.evaluate("document.activeElement && document.activeElement.matches('#plan-sheet input')"), "no switch starts with a focus ring"
    expect(sheet.get_by_text("Mutual Funds")).to_have_count(0)  # only the three sections, no accounts
    expect(sheet.locator("input.toggle")).to_have_count(3)
    sheet.locator('input[name="build"]').uncheck()
    sheet.locator('input[name="build"]').check()
    sheet.get_by_role("button", name="Done").click()
    page.wait_for_url(re.compile(r"/plan"))
    expect(page.locator(".cat-chips .chip")).to_have_text(["Spend", "Build", "Earn"])
    page.locator(".cat-chips .chip", has_text="Build").click()
    expect(page.locator("[data-budget-saving] a.catrow", has_text="Mutual Funds")).to_be_visible()
    page.get_by_role("link", name="Choose what to plan").click()
    page.locator('#plan-sheet input[name="earn"]').uncheck()
    page.locator('#plan-sheet input[name="build"]').uncheck()
    page.locator("#plan-sheet").get_by_role("button", name="Done").click()
    page.wait_for_url(re.compile(r"tab=spend"))
    expect(page.locator(".cat-chips .chip")).to_have_count(0)  # only Spend: no chips, the button stays
    expect(page.get_by_role("link", name="Choose what to plan")).to_be_visible()
