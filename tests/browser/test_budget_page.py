"""The budget page in a browser: assigning in place, copying last month, what is ready to assign."""

from datetime import date, timedelta

from playwright.sync_api import Page, expect

from .conftest import Api

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def ready(page: Page) -> str:
    return page.locator(".ready .figure").inner_text()


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
    assert ready(page).startswith("5,000.00")
    assign_in_sheet(page, "Groceries", "1200")
    expect(page.locator(".ready .figure")).to_have_text("3,800.00 INR")
    page.locator("a.catrow", has_text="Groceries").first.click()
    assert page.locator('#cat-sheet input[aria-label="Assigned to Groceries"]').input_value() == "1,200.00"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone"


def test_copying_last_months_amounts(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['food']['aid']}", month=LAST_MONTH.isoformat(), amount="300")
    api.put(f"/budget/categories/{books['rent']['aid']}", month=LAST_MONTH.isoformat(), amount="900")
    page.goto("/budget")
    page.locator("details.attn > summary").click()
    button = page.get_by_role("button", name="Copy last month's amounts")
    expect(button).to_contain_text("1,200.00")
    button.click()
    expect(button).to_have_count(0)
    page.locator("a.catrow", has_text="Rent").first.click()
    assert page.locator('#cat-sheet input[aria-label="Assigned to Rent"]').input_value() in ("900.00", "900")


def test_a_target_shows_what_is_missing_and_funding_fills_it(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['rent']['aid']}/target", kind="monthly", amount="800")
    page.goto("/budget")
    expect(page.locator("a.catrow .cap.short")).to_contain_text("needs 800.00 more")
    page.locator("details.attn > summary").click()
    page.get_by_role("button", name="Assign what is needed").click()
    expect(page.locator("a.catrow .cap.short")).to_have_count(0)
    expect(page.locator(".ready .figure")).to_have_text("4,200.00 INR")


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
    expect(page.locator(".ready .figure")).to_have_text("4,500.00 INR")
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


def test_a_group_folds_opens_remembers_and_takes_money_for_itself(page: Page, books, api: Api):
    dining = api.post("/accounts/", name="Dining", parent_id=books["roots"]["Expenses"])
    api.post("/accounts/", name="Delivery", parent_id=dining["aid"])
    api.post("/accounts/", name="Restaurant", parent_id=dining["aid"])
    page.goto("/budget")
    group = page.locator("details.grp", has_text="Dining").first
    expect(page.locator("a.catrow", has_text="Delivery")).to_be_hidden()
    group.locator("summary").click()
    expect(page.locator("a.catrow", has_text="Delivery")).to_be_visible()
    page.reload()
    expect(page.locator("a.catrow", has_text="Delivery")).to_be_visible()  # remembered
    # money for the group itself, not in a sub-category
    page.locator("a.catrow", has_text="Everything else").first.click()
    box = page.locator('#cat-sheet input[aria-label^="Assigned to"]')
    expect(page.locator("#cat-sheet")).to_contain_text("Dining · everything else")
    box.fill("700")
    page.locator("#cat-sheet").get_by_role("button", name="Save").click()
    expect(page.locator(".ready .figure")).to_have_text("4,300.00 INR")
    expect(page.locator("a.catrow", has_text="Delivery")).to_be_visible()  # still open after the page block was replaced
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_month_tick_on_a_budget_bar_is_a_vertical_line_not_a_clipped_dot(page: Page, books):
    page.goto("/budget")
    tick = page.locator("a.catrow .pace").first
    expect(tick).to_be_visible()
    box = tick.bounding_box()
    assert box["height"] >= 10 and box["width"] <= 4, f"a tall thin line, not a dot: {box}"
    bar = page.locator("a.catrow .bar").first
    assert bar.evaluate("e => getComputedStyle(e).overflow") == "visible", "the bar must not clip the tick"
