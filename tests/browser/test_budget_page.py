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
