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


def test_a_touched_row_is_not_painted_grey(page: Page, books):
    """A tap or the start of a scroll leaves :hover on in touch browsers: rows must not turn into a grey rectangle."""
    page.goto("/settings")
    for row in (page.locator("details.setting > summary").first, page.locator("a.setting-link").first):
        row.hover()
        assert page.evaluate("el => getComputedStyle(el).backgroundColor", row.element_handle()) in ("rgba(0, 0, 0, 0)", "transparent")
    # and the hover colours that remain are only for devices that really hover
    css = page.request.get(page.evaluate("document.querySelector('link[rel=stylesheet]').href")).text()
    assert "@media (hover: hover) { .account-row:hover" in css and ".setting > summary:hover" not in css


def test_values_sit_beside_the_chevron_and_sign_out_is_a_red_row(page: Page, books):
    page.goto("/settings")
    for row in ("#currency", "#appearance"):
        value = page.locator(f"{row} .setting-value").bounding_box()
        chevron = page.locator(f"{row} summary .icon").bounding_box()
        assert 0 <= chevron["x"] - (value["x"] + value["width"]) <= 12, f"{row}: the value is right beside the chevron"
    out = page.get_by_role("button", name="Sign out")
    expect(out).to_be_visible()
    assert out.evaluate("e => getComputedStyle(e).color") != page.locator("#currency .setting-title").evaluate("e => getComputedStyle(e).color")
    assert out.bounding_box()["width"] > 200, "a full row, not a small pill"
