"""The built-in groups in a browser: the form following the kind chosen."""

import re

import pytest
from playwright.sync_api import Page, expect

from app.services import account as account_service


@pytest.fixture(autouse=True)
def with_groups(monkeypatch):
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)


def test_an_empty_page_shows_the_five_shelves_and_each_starts_an_account_of_its_kind(page: Page):
    page.goto("/accounts")
    expect(page.locator(".acc-head h2")).to_have_text(["Bank Accounts", "Cash", "Credit Cards", "Investments", "Loans"])
    page.locator("section.acc-kind").first.get_by_role("link", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/new\?parent="))
    expect(page.locator("[data-kind-chip][aria-pressed='true']")).to_have_text("Bank Accounts")
    page.locator('input[name="name"]').fill("HDFC")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    page.goto("/accounts")
    expect(page.locator(".acc-head p").first).to_contain_text("1 account")


def test_a_groups_own_page_adds_inside_it(page: Page, api):
    group = next(a for a in api.get("/accounts/") if a["name"] == "Investments")
    page.goto(f"/accounts/{group['id']}")
    page.get_by_role("link", name="Add account").click()
    page.wait_for_url("**/accounts/new?parent=*")
    expect(page.locator("[data-kind-chip][aria-pressed='true']")).to_have_text("Investments")
    expect(page.locator('input[name="on_budget"]')).not_to_be_checked()  # Investments: outside the budget


def choose(page: Page, name: str) -> None:
    """Pick a kind by its chip."""
    page.locator("[data-kind-chip]", has_text=name).click()


def test_the_budget_line_follows_the_group_chosen(page: Page):
    page.goto("/accounts/new")
    box = page.locator('input[name="on_budget"]')
    choose(page, "Bank Accounts")
    expect(box).to_be_checked()
    choose(page, "Investments")
    expect(box).not_to_be_checked()
    choose(page, "Cash")
    expect(box).to_be_checked()
    page.locator('input[name="name"]').fill("Wallet")
    page.get_by_role("button", name="Add account").click()
    page.wait_for_url(re.compile(r"/accounts/[0-9a-f-]{36}$"))
    page.goto("/accounts")
    expect(page.locator("a.acc-card", has_text="Wallet")).to_be_visible()
