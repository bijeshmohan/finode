"""Connecting assistants with OAuth: Supabase issues the tokens, finode keeps what each app may do."""

from uuid import UUID

import httpx2
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from finode.config import settings
from finode.main import app
from finode.mcp_server import transport
from finode.repositories.oauth_grant import OAuthGrantRepository
from finode.services.oauth_grant import OAuthGrantService
from tests.books import post_account
from tests.conftest import TEST_USER_ID
from tests.mcputil import ToolFailed, mcp_client, payload, running_app

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
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
    }
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
        OAuthGrantService(OAuthGrantRepository(session, TEST_USER_ID)).revoke(grant.id)
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
    _bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "100"}).json()
    post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]})
    async with running_app(session), mcp_client(app_token(jwts)) as c:
        recorded = payload(
            await c.call_tool("record_transaction", {"amount": "9", "from_account": "Bank", "to_account": "Food"})
        )
    assert recorded["recorded"]["created_via"] == "assistant (Claude on phone)"


def test_an_apps_token_is_not_a_sign_in_for_the_json_api(session, monkeypatch):
    from finode.auth import identity as auth

    monkeypatch.setattr(auth, "verify_supabase_jwt", lambda token: {"sub": str(TEST_USER_ID), "client_id": "client-1"})
    from finode.auth.identity import require_authenticated_user

    app.dependency_overrides.pop(require_authenticated_user, None)
    with TestClient(app) as plain:
        response = plain.get("/api/accounts/", headers={"Authorization": "Bearer jwt-app"})
    assert response.status_code == 401 and "connected app" in response.json()["detail"]
