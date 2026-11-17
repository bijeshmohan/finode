"""The React app's AI assistants page and consent screen in a browser: a token made here shows its secret once and works,
revoking stops it, access changes, and the consent screen sends the browser back to the app (Supabase's authorization
stood in for, as tests/api/test_api_assistants.py does)."""

import re

import pytest
from playwright.sync_api import Page, expect

from finode.auth import oauth

CALLBACK = "https://claude.ai/callback"


def item(page: Page, name: str):
    return page.locator("main li", has=page.get_by_text(name, exact=True))


INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
}


def mcp_status(page: Page, secret: str) -> int:
    """What /mcp answers an assistant's first call made with the token."""
    answer = page.request.post(
        "/mcp/",
        data=INITIALIZE,
        headers={
            "Authorization": f"Bearer {secret}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
    )
    return answer.status


def make_token(page: Page, name: str, access: str = "Read") -> str:
    page.goto("/profile/assistants")
    page.locator("main").get_by_role("button", name=re.compile("^Use a token")).click()
    page.get_by_label("Name").fill(name)
    page.get_by_role("radio", name=access).check()
    page.get_by_role("button", name="Create token").click()
    expect(page.get_by_role("heading", name=f"{name} is ready")).to_be_visible()
    return page.locator("#token-secret").inner_text()


def test_a_token_shows_its_secret_once_works_and_stops_when_revoked(
    signed_in_page: Page, server: str, session, monkeypatch: pytest.MonkeyPatch
):
    from contextlib import nullcontext

    from finode.mcp_server import context

    monkeypatch.setattr(context, "session_factory", lambda: nullcontext(session))  # /mcp reads the test's books
    page = signed_in_page
    secret = make_token(page, "Cursor")
    assert secret
    expect(page.locator("main")).to_contain_text(f"Bearer {secret}")
    expect(item(page, "Cursor")).to_contain_text("read only")
    assert mcp_status(page, secret) == 200, "the token works for an assistant"
    page.goto("/settings")
    page.goto("/profile/assistants")
    expect(page.locator("main")).not_to_contain_text(secret)
    page.once("dialog", lambda dialog: dialog.accept())
    item(page, "Cursor").get_by_role("button", name="Revoke").click()
    expect(page.get_by_text("Token revoked. Assistants using it can no longer connect.")).to_be_visible()
    expect(item(page, "Cursor")).to_have_count(0)
    assert mcp_status(page, secret) == 401, "a revoked token stops at once"


def test_changing_a_tokens_access(signed_in_page: Page):
    page = signed_in_page
    make_token(page, "Claude Desktop")
    page.once("dialog", lambda dialog: dialog.accept())
    item(page, "Claude Desktop").get_by_role("button", name="Allow changes").click()
    expect(page.get_by_text("Access updated. It applies to the very next request.")).to_be_visible()
    expect(item(page, "Claude Desktop")).to_contain_text("read & write")
    item(page, "Claude Desktop").get_by_role("button", name="Make read only").click()
    expect(item(page, "Claude Desktop")).to_contain_text("read only")


@pytest.fixture
def supabase(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict = {"decide": []}

    def details(authorization_id: str, token: str) -> oauth.AuthorizationDetails:
        return oauth.AuthorizationDetails(
            authorization_id=authorization_id,
            client_id="client-1",
            client_name="Claude",
            client_uri="https://claude.ai",
            redirect_uri=CALLBACK,
            scopes=("openid",),
        )

    def decide(authorization_id: str, approve: bool, token: str) -> str:
        calls["decide"].append((authorization_id, approve))
        return f"{CALLBACK}?code=x"

    monkeypatch.setattr(oauth, "authorization_details", details)
    monkeypatch.setattr(oauth, "decide", decide)
    return calls


def back_at_the_app(page: Page) -> None:
    """The app's own address answers with a plain page, so the test can see the browser got there."""
    page.route(f"{CALLBACK}**", lambda route: route.fulfill(status=200, body="back at the app"))


def test_allowing_an_app_records_it_and_sends_the_browser_back(signed_in_page: Page, supabase: dict):
    page = signed_in_page
    back_at_the_app(page)
    page.goto("/oauth/consent?authorization_id=auth-1")
    expect(page.get_by_role("heading", name="Connect Claude?")).to_be_visible()
    expect(page.locator("main")).to_contain_text(f"you'll be sent back to {CALLBACK}")
    page.get_by_role("button", name="Allow read & write").click()
    page.wait_for_url(f"{CALLBACK}?code=x")
    assert supabase["decide"] == [("auth-1", True)]
    page.goto("/profile/assistants")
    expect(item(page, "Claude")).to_contain_text("read & write")


def test_a_signed_out_arrival_signs_in_and_comes_back(page: Page, supabase: dict):
    page.goto("/oauth/consent?authorization_id=auth-1")
    page.wait_for_url(re.compile(r"/sign-in\?next="))
    page.get_by_label("Email").fill("a@b.co")
    page.get_by_label("Password").fill("right")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Connect Claude?")).to_be_visible()
    expect(page).to_have_url(re.compile(r"/oauth/consent\?authorization_id=auth-1$"))


def test_denying_sends_the_browser_back_and_records_nothing(signed_in_page: Page, supabase: dict):
    page = signed_in_page
    back_at_the_app(page)
    page.goto("/oauth/consent?authorization_id=auth-1")
    page.get_by_role("button", name="Deny").click()
    page.wait_for_url(f"{CALLBACK}?code=x")
    assert supabase["decide"] == [("auth-1", False)]
    page.goto("/profile/assistants")
    expect(page.get_by_text("Nothing connected yet.")).to_be_visible()
