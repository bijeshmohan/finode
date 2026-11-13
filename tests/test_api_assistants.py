"""/api/assistants and /api/oauth/consent: the finode app's Assistants page and the consent screen. Signed in to the app
only (the cookie session): a token alone can never mint tokens or connect apps."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app import oauth
from app.auth import require_cookie_session
from app.main import app


def details(authorization_id: str, token: str, name: str = "Claude") -> oauth.AuthorizationDetails:
    return oauth.AuthorizationDetails(
        authorization_id=authorization_id,
        client_id="client-1",
        client_name=name,
        client_uri="https://claude.ai",
        redirect_uri="https://claude.ai/callback",
        scopes=("openid",),
    )


@pytest.fixture
def supabase(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict = {"decide": [], "revoke": []}
    monkeypatch.setattr(oauth, "authorization_details", details)

    def decide(authorization_id: str, approve: bool, token: str) -> str:
        calls["decide"].append((authorization_id, approve, token))
        return calls.get("redirect", "https://claude.ai/callback?code=x")

    monkeypatch.setattr(oauth, "decide", decide)
    monkeypatch.setattr(oauth, "revoke_grant", lambda client_id, token: calls["revoke"].append((client_id, token)))
    return calls


def test_make_list_change_and_revoke_a_token(client: TestClient):
    made = client.post("/api/assistants/tokens", json={"name": "Laptop", "scope": "read"})
    assert made.status_code == 201 and made.json()["secret"].startswith("fin_")
    token_id = made.json()["id"]
    page = client.get("/api/assistants/").json()
    assert page["mcp_url"].endswith("/mcp")
    assert [(t["name"], t["scope"]) for t in page["tokens"]] == [("Laptop", "read")]
    assert "secret" not in page["tokens"][0]
    changed = client.post(f"/api/assistants/tokens/{token_id}/access", json={"scope": "write"})
    assert changed.json()["scope"] == "write"
    assert client.post(f"/api/assistants/tokens/{token_id}/revoke").status_code == 200
    assert client.get("/api/assistants/").json()["tokens"] == []


def test_a_bad_scope_is_refused(client: TestClient):
    assert client.post("/api/assistants/tokens", json={"name": "x", "scope": "everything"}).status_code == 422
    token_id = client.post("/api/assistants/tokens", json={"name": "x"}).json()["id"]
    assert client.post(f"/api/assistants/tokens/{token_id}/access", json={"scope": "root"}).status_code == 400


def test_bearer_cannot_mint_tokens(client: TestClient):
    """Without the app's cookie session, a signed-in bearer token is refused."""
    app.dependency_overrides.pop(require_cookie_session)
    response = client.post("/api/assistants/tokens", json={"name": "x"}, headers={"Authorization": "Bearer some-token"})
    assert response.status_code == 401


def test_consent_shows_the_app(client: TestClient, supabase: dict):
    seen = client.get("/api/oauth/consent/auth-1").json()
    assert seen["client_name"] == "Claude" and seen["redirect_url"] is None and seen["scopes"] == ["openid"]


def test_consent_allow_records_the_app_supabase_names(client: TestClient, supabase: dict):
    answer = client.post("/api/oauth/consent/auth-1", json={"decision": "allow", "access": "write"})
    assert answer.status_code == 200 and answer.json()["redirect_url"].startswith("https://claude.ai/")
    assert supabase["decide"] == [("auth-1", True, "test-access-token")]
    apps = client.get("/api/assistants/").json()["apps"]
    assert [(a["client_name"], a["scope"]) for a in apps] == [("Claude", "write")]


def test_consent_deny_records_nothing(client: TestClient, supabase: dict):
    assert client.post("/api/oauth/consent/auth-1", json={"decision": "deny"}).status_code == 200
    assert supabase["decide"] == [("auth-1", False, "test-access-token")]
    assert client.get("/api/assistants/").json()["apps"] == []


def test_consent_refuses_a_non_web_redirect(client: TestClient, supabase: dict):
    supabase["redirect"] = "javascript:alert(1)"
    answer = client.post("/api/oauth/consent/auth-1", json={"decision": "deny"})
    assert answer.status_code == 400
    assert answer.json()["detail"] == "The app asked to be opened in a way finode does not allow."


def test_consent_when_supabase_refuses(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def refused(authorization_id: str, token: str) -> oauth.AuthorizationDetails:
        raise oauth.OAuthError("this authorization request is unknown or has expired: start again from the app!")

    monkeypatch.setattr(oauth, "authorization_details", refused)
    answer = client.get("/api/oauth/consent/auth-1")
    assert answer.status_code == 400 and "unknown or has expired" in answer.json()["detail"]


def test_change_and_disconnect_an_app(client: TestClient, supabase: dict):
    client.post("/api/oauth/consent/auth-1", json={"decision": "allow", "access": "read"})
    grant_id = client.get("/api/assistants/").json()["apps"][0]["id"]
    assert client.post(f"/api/assistants/apps/{grant_id}/access", json={"scope": "manage"}).json()["scope"] == "manage"
    assert client.post(f"/api/assistants/apps/{grant_id}/disconnect").status_code == 204
    assert supabase["revoke"] == [("client-1", "test-access-token")]
    assert client.get("/api/assistants/").json()["apps"] == []


def test_unknown_ids(client: TestClient):
    missing = uuid4()
    for path in (
        f"/api/assistants/tokens/{missing}/revoke",
        f"/api/assistants/apps/{missing}/disconnect",
    ):
        assert client.post(path).status_code == 404, path
    for path in (f"/api/assistants/tokens/{missing}/access", f"/api/assistants/apps/{missing}/access"):
        assert client.post(path, json={"scope": "read"}).status_code == 404, path
