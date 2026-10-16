"""The settings page in a browser: saving a setting shows the new value (the page really reloads)."""

from playwright.sync_api import Page, expect


def test_saving_the_currency_shows_the_new_one(page: Page, books):
    page.goto("/settings")
    expect(page.locator("#currency .setting-value")).to_have_text("INR")
    page.locator("#currency summary").click()
    page.select_option('#currency select[name="currency"]', "USD")
    page.get_by_role("button", name="Save currency").click()
    expect(page.locator("#currency .setting-value")).to_have_text("USD")
    expect(page.locator("#currency")).to_have_attribute("open", "")  # and its row is open on the way back


def test_the_advanced_switch_sits_in_the_middle_of_its_row(page: Page, books):
    page.goto("/settings/advanced")
    switch = page.locator("button.switch").bounding_box()
    text = page.locator(".switch-row > div").bounding_box()
    assert abs((switch["y"] + switch["height"] / 2) - (text["y"] + text["height"] / 2)) <= 1.5


def test_a_touched_row_is_not_painted_grey(page: Page, books):
    """A tap or the start of a scroll leaves :hover on in touch browsers: rows must not turn into a grey rectangle."""
    page.goto("/settings")
    for row in (page.locator("details.setting > summary").first, page.locator("a.setting-link").first):
        row.hover()
        assert page.evaluate("el => getComputedStyle(el).backgroundColor", row.element_handle()) in ("rgba(0, 0, 0, 0)", "transparent")
    # and the hover colours that remain are only for devices that really hover
    css = page.request.get(page.evaluate("document.querySelector('link[rel=stylesheet]').href")).text()
    assert "@media (hover: hover) { .account-row:hover" in css and ".setting > summary:hover" not in css
