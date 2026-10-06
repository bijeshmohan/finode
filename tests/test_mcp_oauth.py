"""Connecting assistants with OAuth: Supabase issues the tokens, finode keeps what each app may do."""

import json
import re
from uuid import UUID

import httpx
import httpx2
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from app import oauth
from app.config import settings
from app.main import app
from app.mcp_server import transport
from app.repositories.oauth_grant import OAuthGrantRepository
from app.services.oauth_grant import OAuthGrantService

from .conftest import TEST_USER_ID
from .mcputil import ToolFailed, mcp_client, payload, running_app
from tests.htmlutil import element, text_of


pytestmark = pytest.mark.anyio

OTHER_USER = UUID("00000000-0000-4000-8000-000000000002")
SUPABASE = "https://proj.supabase.co"
AUTH_ID = "auth-123"


@pytest.fixture(autouse=True)
def supabase(monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", SUPABASE)
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")


@pytest.fixture
def jwts(monkeypatch):
    """Stand-ins for the access tokens Supabase would issue: token text -> claims."""
    known: dict[str, dict] = {}

    def verify(token: str) -> dict:
        if token not in known:
            raise HTTPException(status_code=401, detail="invalid authentication token")
        return known[token]

    monkeypatch.setattr(transport, "verify_supabase_jwt", verify)
    return known


def app_token(jwts, user=TEST_USER_ID, client="client-1", token="jwt-app"):
    jwts[token] = {"sub": str(user), "client_id": client, "aud": "authenticated"}
    return token


def allow(session, client="client-1", name="Claude", scope="write", user=TEST_USER_ID):
    service = OAuthGrantService(OAuthGrantRepository(session, user))
    return service.allow(client, name, scope)


async def raw_post(token: str | None):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
    async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="https://finode.example") as http:
        return await http.post("/mcp", json=init, headers=headers)


# ---- discovery -------------------------------------------------------------------------------------


def test_protected_resource_metadata_points_at_supabase(client):
    for path in ("/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"):
        body = client.get(path).json()
        assert body["authorization_servers"] == [f"{SUPABASE}/auth/v1"]
        assert body["resource"].endswith("/mcp") and body["bearer_methods_supported"] == ["header"]


async def test_a_refused_request_says_where_to_find_the_metadata(session):
    async with running_app(session):
        response = await raw_post(None)
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert 'resource_metadata="https://finode.example/.well-known/oauth-protected-resource/mcp"' in challenge


# ---- using an app's token ---------------------------------------------------------------------------


async def test_an_allowed_app_can_use_mcp(session, jwts, root_accounts):
    allow(session, scope="write")
    token = app_token(jwts)
    async with running_app(session), mcp_client(token) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"get_overview", "record_transaction"} <= names
        assert payload(await c.call_tool("get_overview", {}))["net_worth"] == "0.00"


async def test_the_users_choice_of_read_only_is_enforced(session, jwts):
    allow(session, scope="read")
    async with running_app(session), mcp_client(app_token(jwts)) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert "get_overview" in names and "record_transaction" in names, "listed, but they only refuse"
        with pytest.raises(ToolFailed, match="read-only"):
            payload(await c.call_tool("record_transaction", {"amount": "1", "from_account": "a", "to_account": "b"}))


async def test_an_app_the_user_never_allowed_is_refused(session, jwts):
    token = app_token(jwts, client="stranger")
    async with running_app(session):
        assert (await raw_post(token)).status_code == 401


async def test_a_disconnected_app_is_refused_and_can_come_back_with_a_new_level(session, jwts):
    grant = allow(session, scope="write")
    token = app_token(jwts)
    async with running_app(session):
        assert (await raw_post(token)).status_code == 200
        OAuthGrantService(OAuthGrantRepository(session, TEST_USER_ID)).revoke(grant.gid)
        assert (await raw_post(token)).status_code == 401
        allow(session, scope="read")
        assert (await raw_post(token)).status_code == 200


async def test_grants_belong_to_the_user_who_gave_them(session, jwts, root_accounts):
    allow(session, client="client-1", user=OTHER_USER, scope="write")
    token = app_token(jwts, user=TEST_USER_ID, client="client-1")
    async with running_app(session):
        assert (await raw_post(token)).status_code == 401, "someone else allowing the app does not allow it for me"


async def test_an_ordinary_sign_in_token_does_not_work_on_mcp(session, jwts):
    jwts["plain"] = {"sub": str(TEST_USER_ID), "aud": "authenticated"}
    async with running_app(session):
        assert (await raw_post("plain")).status_code == 401
        assert (await raw_post("not-a-token")).status_code == 401


async def test_marks_name_the_app(session, jwts, client, root_accounts):
    allow(session, name="Claude on phone", scope="write")
    bank = client.post("/accounts/", json={"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "100"}).json()
    client.post("/accounts/", json={"name": "Food", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(app_token(jwts)) as c:
        recorded = payload(await c.call_tool("record_transaction", {"amount": "9", "from_account": "Bank", "to_account": "Food"}))
    assert recorded["recorded"]["created_via"] == "assistant (Claude on phone)"


def test_an_apps_token_is_not_a_sign_in_for_the_json_api(session, monkeypatch):
    from app import auth

    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda token: {"sub": str(TEST_USER_ID), "client_id": "client-1"})
    from app.auth import require_authenticated_user

    app.dependency_overrides.pop(require_authenticated_user, None)
    with TestClient(app) as plain:
        response = plain.get("/accounts/", headers={"Authorization": "Bearer jwt-app"})
    assert response.status_code == 401 and "connected app" in response.json()["detail"]


# ---- the consent page ------------------------------------------------------------------------------


class FakeSupabase:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.details = {
            "authorization_id": AUTH_ID,
            "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            "client": {"id": "client-1", "name": "Claude", "uri": "https://claude.ai"},
            "scope": "openid email",
        }
        self.status = 200

    def __call__(self, method, url, headers=None, timeout=None, **kwargs):
        self.calls.append((method, url, {"headers": headers, **kwargs}))
        request = httpx.Request(method, url)
        if self.status != 200:
            return httpx.Response(self.status, json={"msg": "nope"}, request=request)
        if url.endswith("/consent"):
            action = kwargs["json"]["action"]
            target = "https://claude.ai/api/mcp/auth_callback?code=abc" if action == "approve" else "https://claude.ai/api/mcp/auth_callback?error=access_denied"
            return httpx.Response(200, json={"redirect_url": target}, request=request)
        if method == "DELETE":
            return httpx.Response(204, request=request)
        return httpx.Response(200, json=self.details, request=request)


@pytest.fixture
def fake(monkeypatch):
    f = FakeSupabase()
    monkeypatch.setattr(oauth.httpx, "request", f)
    return f


@pytest.fixture
def consent_client(client):
    """The test client skips cookie sign-in; the consent step needs the user's token from request state."""
    from app.web_auth import web_login_required

    def login(request: Request):
        request.state.access_token = "user-jwt"

    app.dependency_overrides[web_login_required] = login
    return client


def test_consent_page_shows_the_app_and_asks_what_it_may_do(consent_client, fake):
    page = consent_client.get(f"/app/oauth/consent?authorization_id={AUTH_ID}")
    assert page.status_code == 200
    assert "Connect Claude?" in page.text and "https://claude.ai/api/mcp/auth_callback" in page.text
    assert 'name="action" value="allow-read"' in page.text and 'name="action" value="allow-write"' in page.text
    assert 'value="deny"' in page.text and "name=\"access\"" not in page.text
    method, url, extra = fake.calls[0]
    assert (method, url) == ("GET", f"{SUPABASE}/auth/v1/oauth/authorizations/{AUTH_ID}")
    assert extra["headers"]["Authorization"] == "Bearer user-jwt" and extra["headers"]["apikey"] == "anon-key"


def test_allowing_records_the_level_and_sends_the_user_back_to_the_app(consent_client, fake, session):
    response = consent_client.post(
        "/app/oauth/consent", data={"authorization_id": AUTH_ID, "action": "allow", "access": "write"}, follow_redirects=False
    )
    assert response.status_code == 303 and response.headers["location"] == "https://claude.ai/api/mcp/auth_callback?code=abc"
    grant = OAuthGrantRepository(session, TEST_USER_ID).by_client("client-1")
    assert (grant.client_name, grant.scope, grant.revoked) == ("Claude", "write", None)
    consent_call = next(c for c in fake.calls if c[1].endswith("/consent"))
    assert consent_call[2]["json"] == {"action": "approve"}


def test_denying_records_nothing(consent_client, fake, session):
    response = consent_client.post(
        "/app/oauth/consent", data={"authorization_id": AUTH_ID, "action": "deny", "access": "write"}, follow_redirects=False
    )
    assert response.status_code == 303 and "error=access_denied" in response.headers["location"]
    assert OAuthGrantRepository(session, TEST_USER_ID).by_client("client-1") is None


def test_the_app_comes_from_supabase_not_the_form(consent_client, fake, session):
    consent_client.post(
        "/app/oauth/consent",
        data={"authorization_id": AUTH_ID, "action": "allow", "access": "read", "client_id": "evil", "client_name": "Evil"},
        follow_redirects=False,
    )
    assert OAuthGrantRepository(session, TEST_USER_ID).by_client("evil") is None
    assert OAuthGrantRepository(session, TEST_USER_ID).by_client("client-1").client_name == "Claude"


def test_problems_are_explained(consent_client, fake):
    assert "Start from the app" in consent_client.get("/app/oauth/consent").text
    fake.status = 404
    page = consent_client.get(f"/app/oauth/consent?authorization_id={AUTH_ID}")
    assert page.status_code == 400 and "unknown or has expired" in page.text
    fake.status = 401
    assert "sign in again" in consent_client.get(f"/app/oauth/consent?authorization_id={AUTH_ID}").text


def test_only_web_urls_are_followed_back(consent_client, fake, monkeypatch):
    monkeypatch.setattr(fake, "details", {**fake.details, "redirect_url": "javascript:alert(1)"})
    page = consent_client.get(f"/app/oauth/consent?authorization_id={AUTH_ID}")
    assert page.status_code == 400 and "does not allow" in page.text
    assert not oauth.is_web_url("javascript:alert(1)") and oauth.is_web_url("https://x.example/cb")


def test_unauthenticated_visitors_sign_in_and_come_back(client):
    app.dependency_overrides.pop(__import__("app.web_auth", fromlist=["x"]).web_login_required, None)
    with TestClient(app) as raw:
        target = f"/app/oauth/consent?authorization_id={AUTH_ID}"
        response = raw.get(target, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/app/login?next=%2Fapp%2Foauth%2Fconsent%3Fauthorization_id%3Dauth-123"
        login = raw.get(response.headers["location"])
        assert f'name="next" value="{target}"' in login.text
        plain = raw.get("/app/login")
        assert 'name="next"' not in plain.text


def test_only_the_consent_page_is_a_login_destination():
    from app.web_auth import safe_next

    assert safe_next("/app/oauth/consent?authorization_id=x") == "/app/oauth/consent?authorization_id=x"
    assert safe_next("/app/oauth/consent") == "/app/oauth/consent"
    for bad in ("https://evil.example", "//evil.example", "/app/profile", "/app/oauth/consentX", "", None):
        assert safe_next(bad) is None


# ---- connected apps on the assistants page ---------------------------------------------------------


def test_connected_apps_are_listed_and_can_be_disconnected(consent_client, fake, session):
    grant = allow(session, name="Claude on phone", scope="read")
    page = consent_client.get("/app/profile/assistants").text
    apps = text_of(element(page, "token-list"))
    assert "Claude on phone" in apps and "read only" in apps
    response = consent_client.post(f"/app/oauth/apps/{grant.gid}/disconnect")
    assert response.headers["HX-Redirect"] == "/app/profile/assistants" and "app-disconnected" in response.headers["set-cookie"]
    assert OAuthGrantRepository(session, TEST_USER_ID).read(grant.gid).revoked is not None
    assert any(m == "DELETE" and "client_id=client-1" in str(e["params"]) or e.get("params") == {"client_id": "client-1"} for m, u, e in fake.calls)
    assert "Claude on phone" not in text_of(element(consent_client.get("/app/profile/assistants").text, "token-list"))
    assert consent_client.post(f"/app/oauth/apps/{UUID(int=9)}/disconnect").status_code == 404


def test_one_user_cannot_disconnect_anothers_app(consent_client, fake, session):
    theirs = allow(session, user=OTHER_USER, name="Theirs")
    assert consent_client.post(f"/app/oauth/apps/{theirs.gid}/disconnect").status_code == 404
    assert OAuthGrantRepository(session, OTHER_USER).read(theirs.gid).revoked is None


def test_each_consent_button_records_its_own_level(consent_client, fake, session):
    for action, scope in (("allow-read", "read"), ("allow-write", "write")):
        response = consent_client.post(
            "/app/oauth/consent", data={"authorization_id": AUTH_ID, "action": action}, follow_redirects=False
        )
        assert response.status_code == 303 and "code=abc" in response.headers["location"]
        from app.repositories.oauth_grant import OAuthGrantRepository

        assert OAuthGrantRepository(session, TEST_USER_ID).by_client("client-1").scope == scope
