"""The built-in groups in a browser: the round + on a group's heading and the form following the group chosen."""

import re

import pytest
from playwright.sync_api import Page, expect

from app.services import account as account_service


@pytest.fixture(autouse=True)
def with_groups(monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)


def test_the_plus_on_a_group_opens_the_form_on_that_group(page: Page):
    page.goto("/accounts")
    expect(page.locator(".acc-gh.fixed")).to_have_count(3)
    page.get_by_role("link", name="Add to Investments").click()
    page.wait_for_url("**/accounts/new?parent=*")
    expect(page.locator('select[name="parent_id"] option:checked')).to_have_text("Investments")
    expect(page.locator("[data-budget-summary]")).to_have_text("Planned under Build")


def choose(page: Page, name: str) -> None:
    """Pick a parent by its name (the options are indented by depth, so the label alone does not match)."""
    value = page.locator("select[name=parent_id] option", has_text=name).first.get_attribute("value")
    page.locator('select[name="parent_id"]').select_option(value=value)


def test_the_budget_line_follows_the_group_chosen(page: Page):
    page.goto("/accounts/new?root=assets")
    summary = page.locator("[data-budget-summary]")
    expect(summary).to_have_text("Part of the budget")  # Bank Accounts
    choose(page, "Investments")
    expect(summary).to_have_text("Planned under Build")
    choose(page, "Cash")
    expect(summary).to_have_text("Part of the budget")
    page.locator('input[name="name"]').fill("Wallet")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    page.goto("/accounts")
    expect(page.locator("li[data-path='assets › cash › wallet']")).to_be_visible()
