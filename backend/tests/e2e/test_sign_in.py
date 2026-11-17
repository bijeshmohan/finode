"""Signing in to the React app in a real browser, through the real /api/auth (only Supabase is stood in for)."""

import re

from playwright.sync_api import Page, expect


def test_the_form_is_centred_and_has_no_card(page: Page):
    page.goto("/sign-in")
    column = page.get_by_role("heading", name="finode").locator("xpath=..")
    expect(column).to_be_visible()
    assert column.evaluate("e => getComputedStyle(e).borderTopWidth") == "0px"
    box = column.bounding_box()
    assert box is not None
    middle = box["y"] + box["height"] / 2
    assert abs(middle - 844 / 2) < 120, f"centred on the page, not at the top: {middle}"
    assert box["x"] >= 16 and box["x"] + box["width"] <= 390 - 16, "a gutter on a phone"


def test_signing_in_takes_you_where_you_were_going(page: Page):
    page.goto("/accounts")
    page.get_by_label("Email").fill("a@b.co")
    page.get_by_label("Password").fill("right")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Accounts")).to_be_visible()
    expect(page).to_have_url(re.compile(r"/accounts$"))


def test_a_wrong_password_says_so(page: Page):
    page.goto("/sign-in")
    page.get_by_label("Email").fill("a@b.co")
    page.get_by_label("Password").fill("wrong")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("alert")).to_have_text("Invalid email or password.")


def test_creating_an_account(page: Page, monkeypatch):
    from finode.auth import flows as auth_flows
    from finode.config import settings

    monkeypatch.setattr(settings, "signup_code", "a-long-enough-invite-code")
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_test_key")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(auth_flows, "create_user", lambda email, password: None)
    page.goto("/sign-up")
    page.get_by_label("Email").fill("new@example.com")
    page.get_by_label("Password", exact=True).fill("right horse")
    page.get_by_label("Confirm password").fill("right horse")
    page.get_by_label("Invite code").fill("a-long-enough-invite-code")
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("heading", name="Home")).to_be_visible()


def test_resetting_a_password(page: Page, monkeypatch):
    from finode.auth import flows as auth_flows
    from finode.auth.session import SessionTokens
    from finode.config import settings

    monkeypatch.setattr(settings, "password_reset", True)
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    monkeypatch.setattr(
        auth_flows, "reset_password", lambda token_hash, password: SessionTokens("test-access", "test-refresh", 3600)
    )
    page.goto("/reset?token_hash=abc")
    page.get_by_label("New password").fill("correct horse")
    page.get_by_label("Confirm password").fill("correct horse")
    page.get_by_role("button", name="Change password").click()
    expect(page.get_by_role("heading", name="Home")).to_be_visible()
    expect(page.get_by_role("status")).to_have_text("Your password was changed. You are signed in.")
