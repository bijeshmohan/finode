"""Settings › Standard groups in a browser, for somebody who already has accounts."""

import re

from playwright.sync_api import Page, expect


def test_the_sheet_lists_what_will_be_added_and_adding_closes_the_row(page: Page, books):
    page.goto("/settings")
    row = page.locator("#groups")
    expect(row).to_be_visible()
    row.click()
    sheet = page.locator("#groups-sheet")
    expect(sheet).to_be_visible()
    expect(sheet.locator(".groups-plan li")).to_have_count(5)
    page.get_by_role("button", name=re.compile(r"(Add|Set up) 5 groups")).click()
    page.wait_for_url("**/settings")
    expect(page.locator("#groups")).to_have_count(0)
    expect(page.locator(".toast")).to_contain_text("Standard groups added")


def test_cancel_closes_the_sheet_and_adds_nothing(page: Page, books, api):
    page.goto("/settings")
    page.locator("#groups").click()
    page.get_by_role("button", name="Cancel").click()
    expect(page.locator("#groups-sheet")).not_to_be_visible()
    assert not any(a["system_key"] for a in api.get("/accounts/"))
