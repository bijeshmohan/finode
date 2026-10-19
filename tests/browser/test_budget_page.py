"""The budget page in a browser: assigning in place, copying last month, what is ready to assign."""

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
    page.goto("/budget")
    assert ready(page) == "\u20b95,000.00"
    assign_in_sheet(page, "Groceries", "1200")
    expect(page.locator(".ready-hero .figure")).to_have_text("\u20b93,800.00")
    page.locator("a.catrow", has_text="Groceries").first.click()
    assert page.locator('#cat-sheet input[aria-label="Assigned to Groceries"]').input_value() == "1,200.00"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone"


def test_copying_last_months_amounts(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['food']['aid']}", month=LAST_MONTH.isoformat(), amount="300")
    api.put(f"/budget/categories/{books['rent']['aid']}", month=LAST_MONTH.isoformat(), amount="900")
    page.goto("/budget")
    page.locator("button.need").click()
    button = page.get_by_role("button", name="Copy last month's amounts")
    expect(button).to_contain_text("1,200.00")
    button.click()
    expect(button).to_have_count(0)
    page.locator("a.catrow", has_text="Rent").first.click()
    assert page.locator('#cat-sheet input[aria-label="Assigned to Rent"]').input_value() in ("900.00", "900")


def test_a_target_shows_what_is_missing_and_funding_fills_it(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['rent']['aid']}/target", kind="monthly", amount="800")
    page.goto("/budget")
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
    page.goto("/budget")
    expect(page.get_by_text("Cards to pay")).to_be_visible()
    expect(page.locator(".cards-list")).to_contain_text("Visa")
    expect(page.locator(".cards-list")).to_contain_text("120.00")
    page.locator("details.how > summary").click()
    expect(page.locator(".calc").first).to_contain_text("set aside for card bills 120.00")
    # Assigning money to a category changes ready to assign, and the explanation follows it.
    assign_in_sheet(page, "Rent", "500")
    expect(page.locator(".ready-hero .figure")).to_have_text("\u20b94,500.00")
    expect(page.locator(".calc").first).to_contain_text("in categories 380.00")


def test_the_target_form_shows_the_fields_each_kind_needs(page: Page, books):
    page.goto(f"/budget/target?category={books['rent']['aid']}")
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
    page.goto(f"/budget/target?category={books['rent']['aid']}")
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
    page.goto("/budget")
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
    page.goto("/budget")
    expect(page.locator("a.catrow", has_text="Delivery")).to_have_count(0)  # inside the group, on its page
    expect(page.locator("a.grow", has_text="Dining")).to_contain_text("Delivery")  # the hint names what is inside
    page.locator("a.grow", has_text="Dining").click()
    page.wait_for_url("**/budget/group/**")
    expect(page.locator("a.catrow", has_text="Delivery")).to_be_visible()
    page.get_by_label("Edit the budget for Dining").click()
    box = page.locator('#cat-sheet input[aria-label="Budget for Dining"]')
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
    page.get_by_role("link", name="Budget", exact=True).first.click()
    expect(page.locator(".ready-hero .figure")).to_have_text("\u20b94,300.00")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_month_tick_on_a_budget_bar_is_a_vertical_line_not_a_clipped_dot(page: Page, books):
    page.goto("/budget")
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
    page.goto("/budget")
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
    page.goto("/budget")
    lefts = page.eval_on_selector_all(".crow-name", "els => els.filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().left))")
    rights = page.eval_on_selector_all(".crow-amt", "els => els.filter(e => e.offsetParent).map(e => Math.round(e.getBoundingClientRect().right))")
    assert len(lefts) >= 2 and len(set(lefts)) == 1, lefts
    assert len(set(rights)) == 1, rights



def test_the_i_opens_the_sum_behind_ready_to_assign_and_survives_assigning(page: Page, books):
    page.goto("/budget")
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
    expect(page.locator(".ready-hero .figure")).to_have_text("₹3,800.00")  # 5,000 - 1,200: it saved
