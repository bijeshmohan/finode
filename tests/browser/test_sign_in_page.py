"""The sign-in page has no card and its form sits in the middle of the page."""

from playwright.sync_api import Page, expect


def test_the_form_is_centred_and_has_no_card(page: Page):
    page.goto("/login")
    card = page.locator("section.narrow")
    expect(card).to_be_visible()
    assert card.evaluate("e => getComputedStyle(e).borderTopWidth") == "0px"
    box = card.bounding_box()
    middle = box["y"] + box["height"] / 2
    assert abs(middle - 844 / 2) < 120, f"centred on the page, not at the top: {middle}"
    assert box["x"] >= 16 and box["x"] + box["width"] <= 390 - 16, "a gutter on a phone"
    page.locator('input[name="email"]').fill("a@b.co")
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()
