"""Offline and a failed save: say what is wrong and never lose what the person typed."""

import re

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def old_entry(api: Api, books: dict) -> dict:
    return api.post(
        "/transactions/",
        payee="Old",
        postings=[leg(books["food"], "debit", "40"), leg(books["checking"], "credit", "40")],
    )


def test_going_offline_shows_a_banner_and_coming_back_hides_it(signed_in_page: Page, books):
    page = signed_in_page
    page.goto("/")
    banner = page.get_by_role("status").filter(has_text="offline")
    expect(banner).to_have_count(0)
    page.context.set_offline(True)
    expect(banner).to_contain_text("You're offline")
    page.context.set_offline(False)
    expect(banner).to_have_count(0)


def test_a_save_that_cannot_reach_the_server_keeps_the_entry_and_says_so(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    entry = old_entry(api, books)
    page.goto(f"/transactions/{entry['id']}/edit")
    page.get_by_label("Payee").fill("Changed")
    failing = {"on": True}
    page.route(
        re.compile(r".*/api/entries/"),
        lambda route: route.abort() if failing["on"] and route.request.method == "PUT" else route.continue_(),
    )
    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_text("finode can't be reached. Check your connection.")).to_be_visible()
    expect(page.get_by_label("Payee")).to_have_value("Changed")
    failing["on"] = False
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url(re.compile(r"/transactions$"))
    assert api.get(f"/transactions/{entry['id']}")["payee"] == "Changed"


def test_a_server_error_is_explained_without_clearing_the_form(signed_in_page: Page, books, api: Api):
    page = signed_in_page
    entry = old_entry(api, books)
    page.goto(f"/transactions/{entry['id']}/edit")
    page.get_by_label("Payee").fill("Changed")
    page.route(
        re.compile(r".*/api/entries/"),
        lambda route: route.fulfill(status=500, body="boom") if route.request.method == "PUT" else route.continue_(),
    )
    page.get_by_role("button", name="Save changes").click()
    expect(page.get_by_text("Something went wrong. Please try again.")).to_be_visible()
    expect(page.get_by_label("Payee")).to_have_value("Changed")
    assert api.get(f"/transactions/{entry['id']}")["payee"] == "Old"
