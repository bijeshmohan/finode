"""The React app in a real browser: the built app and the API on one address (see tests/browser/spa.py)."""

import re

from playwright.sync_api import Page, expect


def test_signed_out_lands_on_sign_in(spa_page: Page):
    spa_page.goto("/accounts")
    expect(spa_page).to_have_url(re.compile(r"/sign-in\?next=%2Faccounts$"))


def test_signed_in_sees_the_tab_bar(signed_in_spa_page: Page):
    signed_in_spa_page.goto("/")
    expect(signed_in_spa_page.get_by_role("navigation", name="Tab bar")).to_be_visible()
    expect(signed_in_spa_page.get_by_role("heading", name="Home")).to_be_visible()


def test_an_unknown_address_is_answered_by_the_app(signed_in_spa_page: Page):
    signed_in_spa_page.goto("/no-such-page")
    expect(signed_in_spa_page.get_by_role("heading", name="Page not found")).to_be_visible()


STATUS_BAR = """[...document.querySelectorAll('meta[name="theme-color"]')]
    .find((m) => !m.media || matchMedia(m.media).matches)?.content ?? null"""


def test_the_phones_status_bar_follows_the_device_as_the_web_pages_do(spa_page: Page):
    """The bar above the page (theme-color) is the page's own colour in light and in dark, as base.html declares."""
    page = spa_page
    for scheme, colour in (("light", "#ecf0ec"), ("dark", "#10151f")):
        page.emulate_media(color_scheme=scheme)
        page.goto("/sign-in")
        assert page.evaluate(STATUS_BAR) == colour, scheme
