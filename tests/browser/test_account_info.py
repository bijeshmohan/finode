"""An account's or category's description sits behind an "i" beside its name."""

from playwright.sync_api import Page, expect

from .conftest import Api


def test_the_description_opens_from_the_i_and_gives_way_to_the_menu(page: Page, api: Api, books):
    food = books["food"]
    response = page.request.patch(f"/api/accounts/{food['aid']}", data={"details": "Weekly shop and the corner store"})
    assert response.ok, response.text()
    page.goto(f"/categories/{food['aid']}")

    note = page.get_by_text("Weekly shop and the corner store")
    expect(note).to_be_hidden()  # nothing under the name: the page starts with the title and the figure
    page.get_by_label("About Groceries").click()
    expect(note).to_be_visible()

    page.get_by_label("More actions").click()
    expect(note).to_be_hidden()  # opening the menu closes the note: they share the place under the title
    expect(page.get_by_text("Delete category")).to_be_visible()

    page.get_by_label("About Groceries").click()
    expect(note).to_be_visible()
    expect(page.get_by_text("Delete category")).to_be_hidden()


def test_no_description_means_no_i(page: Page, api: Api, books):
    page.goto(f"/accounts/{books['cash']['aid']}")
    expect(page.get_by_role("heading", name="Cash")).to_be_visible()
    expect(page.get_by_label("About Cash")).to_have_count(0)
