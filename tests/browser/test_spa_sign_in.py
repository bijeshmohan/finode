"""Signing in to the React app in a real browser, through the real /api/auth (only Supabase is stood in for)."""

import re

from playwright.sync_api import Page, expect


def test_the_form_is_centred_and_has_no_card(spa_page: Page):
    spa_page.goto("/sign-in")
    column = spa_page.get_by_role("heading", name="finode").locator("xpath=..")
    expect(column).to_be_visible()
    assert column.evaluate("e => getComputedStyle(e).borderTopWidth") == "0px"
    box = column.bounding_box()
    assert box is not None
    middle = box["y"] + box["height"] / 2
    assert abs(middle - 844 / 2) < 120, f"centred on the page, not at the top: {middle}"
    assert box["x"] >= 16 and box["x"] + box["width"] <= 390 - 16, "a gutter on a phone"


def test_signing_in_takes_you_where_you_were_going(spa_page: Page):
    spa_page.goto("/accounts")
    spa_page.get_by_label("Email").fill("a@b.co")
    spa_page.get_by_label("Password").fill("right")
    spa_page.get_by_role("button", name="Sign in").click()
    expect(spa_page.get_by_role("heading", name="Accounts")).to_be_visible()
    expect(spa_page).to_have_url(re.compile(r"/accounts$"))


def test_a_wrong_password_says_so(spa_page: Page):
    spa_page.goto("/sign-in")
    spa_page.get_by_label("Email").fill("a@b.co")
    spa_page.get_by_label("Password").fill("wrong")
    spa_page.get_by_role("button", name="Sign in").click()
    expect(spa_page.get_by_role("alert")).to_have_text("Invalid email or password.")
