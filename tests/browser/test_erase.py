"""Erasing your books and deleting your account, as a person does it."""

from playwright.sync_api import Page, expect

from app.routers.web import profile as profile_router

from .conftest import Api


def test_erasing_the_books(page: Page, books, api: Api):
    assert api.get("/accounts/"), "there are accounts to erase"
    page.goto("/profile/data")
    page.locator("#erase summary", has_text="Erase my books").click()
    form = page.locator('form[hx-post="/profile/data/erase"]')
    page.once("dialog", lambda dialog: dialog.accept())
    form.locator('input[name="confirm"]').fill("nobody@example.com")
    form.get_by_role("button", name="Erase my books").click()
    expect(page.locator("#erase-error")).to_have_text("Type test@example.com to confirm.")
    assert api.get("/accounts/"), "a wrong confirmation erases nothing"
    page.once("dialog", lambda dialog: dialog.accept())
    form.locator('input[name="confirm"]').fill("test@example.com")
    form.get_by_role("button", name="Erase my books").click()
    page.wait_for_url("**/")
    expect(page.get_by_text("Your books were erased")).to_be_visible()
    assert [a["name"] for a in api.get("/accounts/") if a["parent_id"]] == [], "only the five types are left"


def test_deleting_the_account(page: Page, books, api: Api, monkeypatch):
    from app.config import settings

    removed = []
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_x")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(profile_router, "delete_user", lambda user_id: removed.append(user_id))
    page.goto("/profile/data")
    page.locator("#erase summary", has_text="Delete my account").click()
    form = page.locator('form[hx-post="/profile/data/delete-account"]')
    page.once("dialog", lambda dialog: dialog.accept())
    form.locator('input[name="confirm"]').fill("test@example.com")
    form.get_by_role("button", name="Delete my account").click()
    page.wait_for_url("**/login")
    expect(page.get_by_text("Your account was deleted")).to_be_visible()
    assert len(removed) == 1
