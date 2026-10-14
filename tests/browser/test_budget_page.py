"""The budget page in a browser: assigning in place, copying last month, what is ready to assign."""

from datetime import date, timedelta

from playwright.sync_api import Page, expect

from .conftest import Api

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def ready(page: Page) -> str:
    return page.locator(".ready .figure").inner_text()


def test_assigning_changes_ready_to_assign_without_a_reload(page: Page, books):
    page.goto("/budget")
    assert ready(page).startswith("5,000.00")
    box = page.locator('input[aria-label="Assigned to Groceries"]')
    box.fill("1200")
    box.press("Tab")  # a decimal keypad has no Return: leaving the field saves it
    expect(page.locator(".ready .figure")).to_have_text("3,800.00 INR")
    assert page.locator('input[aria-label="Assigned to Groceries"]').input_value() == "1,200.00" or "1200" in page.locator('input[aria-label="Assigned to Groceries"]').input_value()


def test_copying_last_months_amounts(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['food']['aid']}", month=LAST_MONTH.isoformat(), amount="300")
    api.put(f"/budget/categories/{books['rent']['aid']}", month=LAST_MONTH.isoformat(), amount="900")
    page.goto("/budget")
    button = page.get_by_role("button", name="Copy last month's amounts")
    expect(button).to_contain_text("1,200.00")
    button.click()
    expect(button).to_have_count(0)
    assert page.locator('input[aria-label="Assigned to Rent"]').input_value() in ("900.00", "900")


def test_a_target_shows_what_is_missing_and_funding_fills_it(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['rent']['aid']}/target", kind="monthly", amount="800")
    page.goto("/budget")
    expect(page.locator(".target-note.short")).to_contain_text("needs 800.00 more")
    page.get_by_role("button", name="Assign what is needed").click()
    expect(page.locator(".target-note.met")).to_contain_text("funded")
    expect(page.locator(".ready .figure")).to_have_text("4,200.00 INR")


def test_a_card_the_budget_includes_is_listed_and_the_sum_is_explained(page: Page, books, api: Api):
    api.post("/transactions/", postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "120"},
        {"account": books["card"]["aid"], "side": "credit", "amount": "120"},
    ])
    page.goto("/budget")
    expect(page.get_by_text("Credit card payments")).to_be_visible()
    expect(page.locator(".cards-list")).to_contain_text("Visa")
    expect(page.locator(".cards-list")).to_contain_text("120.00")
    expect(page.locator(".calc").first).to_contain_text("set aside for card bills 120.00")
    # Assigning money to a category changes ready to assign, and the explanation follows it.
    box = page.locator('input[aria-label="Assigned to Rent"]')
    box.fill("500")
    box.press("Tab")
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
    expect(page.locator(".target-note.short")).to_contain_text("Weekly 100.00 on Fris")


def test_a_weekly_target_opens_into_its_weeks(page: Page, books, api: Api):
    api.put(f"/budget/categories/{books['food']['aid']}/target", kind="weekly", amount="100", weekday=THIS_MONTH.weekday())
    api.post("/transactions/", date=str(THIS_MONTH), postings=[
        {"account": books["food"]["aid"], "side": "debit", "amount": "130"},
        {"account": books["checking"]["aid"], "side": "credit", "amount": "130"},
    ])
    page.goto("/budget")
    weeks = page.locator("details.weeks").first
    expect(weeks.locator("li").first).to_be_hidden()  # closed until opened
    weeks.locator("summary").click()
    expect(weeks.locator("li").first).to_contain_text("130.00 of 100.00")
    expect(weeks.locator("li.over")).to_have_count(1)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "no sideways scrolling on a phone"
