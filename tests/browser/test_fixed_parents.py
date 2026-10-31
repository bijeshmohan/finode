"""The built-in groups in a browser: the round + on a group's heading and the form following the group chosen."""

import re

import pytest
from playwright.sync_api import Page, expect

from app.services import account as account_service


@pytest.fixture(autouse=True)
def with_groups(monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)


def test_an_empty_page_offers_an_add_account_pill_and_shows_no_groups(page: Page):
    page.goto("/accounts")
    expect(page.locator(".acc-gh")).to_have_count(0)
    page.get_by_role("link", name="Add account").last.click()
    page.wait_for_url("**/accounts/new?root=assets")
    expect(page.locator('select[name="parent_id"] option:checked')).to_have_text(re.compile("Bank Accounts"))
    page.locator('input[name="name"]').fill("HDFC")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    page.goto("/accounts")
    expect(page.locator(".acc-gh")).to_have_count(1)
    expect(page.locator(".acc-gh")).to_contain_text("Bank Accounts")


def test_a_groups_own_page_adds_inside_it(page: Page, api):
    group = next(a for a in api.get("/accounts/") if a["name"] == "Investments")
    page.goto(f"/accounts/{group['id']}")
    page.locator(".section-head .circ-button").click()
    page.wait_for_url("**/accounts/new?parent=*")
    expect(page.locator('select[name="parent_id"] option:checked')).to_have_text(re.compile("Investments"))
    expect(page.locator("[data-budget-summary]")).to_have_text("Outside the budget")


def choose(page: Page, name: str) -> None:
    """Pick a parent by its name (the options are indented by depth, so the label alone does not match)."""
    value = page.locator("select[name=parent_id] option", has_text=name).first.get_attribute("value")
    page.locator('select[name="parent_id"]').select_option(value=value)


def test_the_budget_line_follows_the_group_chosen(page: Page):
    page.goto("/accounts/new?root=assets")
    summary = page.locator("[data-budget-summary]")
    expect(summary).to_have_text("Part of the budget")  # Bank Accounts
    choose(page, "Investments")
    expect(summary).to_have_text("Outside the budget")
    choose(page, "Cash")
    expect(summary).to_have_text("Part of the budget")
    page.locator('input[name="name"]').fill("Wallet")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    page.goto("/accounts")
    expect(page.locator("li[data-path='assets › cash › wallet']")).to_be_visible()
