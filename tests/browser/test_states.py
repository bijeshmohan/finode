"""Offline, a failed save and loading: say what is wrong and never lose what the person typed."""

import re

from playwright.sync_api import Page, expect

from ..books import leg
from .conftest import Api


def test_going_offline_shows_a_banner_and_coming_back_hides_it(page: Page, books):
    page.goto("/")
    banner = page.locator("#net-banner")
    expect(banner).to_be_hidden()
    page.context.set_offline(True)
    expect(banner).to_contain_text("You’re offline")
    page.context.set_offline(False)
    expect(banner).to_be_hidden()


def test_a_save_that_cannot_reach_the_server_keeps_the_entry_and_says_so(page: Page, books, api: Api):
    entry = api.post(
        "/transactions/",
        payee="Old",
        postings=[
            leg(books["food"], "debit", "40"),
            leg(books["checking"], "credit", "40"),
        ],
    )
    page.goto(f"/transactions/{entry['tid']}/edit")
    page.fill("#payee", "Changed")
    failing = {"on": True}
    page.route(
        re.compile(r".*/edit$"),
        lambda route: route.abort() if failing["on"] and route.request.method == "POST" else route.continue_(),
    )
    page.get_by_role("button", name="Save changes").click()
    expect(page.locator("#net-banner")).to_contain_text("Couldn’t save just now")
    assert page.input_value("#payee") == "Changed", "what was typed is still there"
    failing["on"] = False
    page.get_by_role("button", name="Save changes").click()
    page.wait_for_url("**/transactions*")
    assert api.get("/transactions/")[0]["payee"] == "Changed"


def test_a_server_error_is_explained_without_clearing_the_form(page: Page, books, api: Api):
    entry = api.post(
        "/transactions/",
        payee="Old",
        postings=[
            leg(books["food"], "debit", "40"),
            leg(books["checking"], "credit", "40"),
        ],
    )
    page.goto(f"/transactions/{entry['tid']}/edit")
    page.fill("#payee", "Changed")
    page.route(
        re.compile(r".*/edit$"),
        lambda route: route.fulfill(status=500, body="boom") if route.request.method == "POST" else route.continue_(),
    )
    page.get_by_role("button", name="Save changes").click()
    expect(page.locator("#net-banner")).to_contain_text("Something went wrong on our side")
    assert page.input_value("#payee") == "Changed"
