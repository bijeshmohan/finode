"""The React app reaches /api with the web session cookie: reads freely, changes only from the app's own origin with
the X-Finode header. A bearer token still works as before, and cookie-only routes refuse it."""

from collections.abc import Generator

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import auth
from app.auth import CookieSession, require_cookie_session
from app.config import settings
from app.dependencies import get_db_session
from app.main import app, cors_options
from app.session import ACCESS_COOKIE, REFRESH_COOKIE, SessionTokens

from .conftest import TEST_USER_ID

FRONTEND = "https://app.example.com"
APP = {"X-Finode": "1", "Origin": FRONTEND}


def fake_verify(token: str) -> dict:
    if token == "good":
        return {"sub": str(TEST_USER_ID), "email": "test@example.com"}
    if token == "app-token":
        return {"sub": str(TEST_USER_ID), "client_id": "some-assistant"}
    raise HTTPException(status_code=401, detail="invalid authentication token")


@pytest.fixture
def raw_client(session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    """Real authentication against fake Supabase answers; only the database is replaced."""
    monkeypatch.setattr(auth, "verify_supabase_jwt", fake_verify)
    monkeypatch.setattr(auth, "refresh_session", lambda token: SessionTokens("good", "new-refresh", 3600))
    monkeypatch.setattr(settings, "frontend_origin", FRONTEND)
    app.dependency_overrides[get_db_session] = lambda: session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def signed_in(client: TestClient, token: str = "good") -> TestClient:
    client.cookies.set(ACCESS_COOKIE, token, path="/")
    return client


def test_a_cookie_reads_the_api(raw_client: TestClient):
    assert signed_in(raw_client).get("/api/profile/").status_code == 200


def test_a_cookie_write_needs_the_header_and_origin(raw_client: TestClient):
    client = signed_in(raw_client)
    change = {"first_name": "A"}
    assert client.patch("/api/profile/", json=change).status_code == 403
    assert client.patch("/api/profile/", json=change, headers={"X-Finode": "1"}).status_code == 403
    evil = {"X-Finode": "1", "Origin": "https://evil.example"}
    assert client.patch("/api/profile/", json=change, headers=evil).status_code == 403
    assert client.patch("/api/profile/", json=change, headers=APP).status_code == 200


def test_an_expired_access_cookie_is_refreshed(raw_client: TestClient):
    raw_client.cookies.set(ACCESS_COOKIE, "expired", path="/")
    raw_client.cookies.set(REFRESH_COOKIE, "r", path="/")
    response = raw_client.get("/api/profile/")
    assert response.status_code == 200
    assert any(c.startswith(f"{REFRESH_COOKIE}=new-refresh") for c in response.headers.get_list("set-cookie"))


def test_without_a_frontend_origin_cookie_writes_are_refused(raw_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "frontend_origin", None)
    client = signed_in(raw_client)
    assert client.get("/api/profile/").status_code == 200
    assert client.patch("/api/profile/", json={"first_name": "A"}, headers=APP).status_code == 403


def test_bearer_skips_the_origin_check(raw_client: TestClient):
    response = raw_client.patch("/api/profile/", json={"first_name": "A"}, headers={"Authorization": "Bearer good"})
    assert response.status_code == 200


def test_an_app_token_in_the_cookie_is_refused(raw_client: TestClient):
    assert signed_in(raw_client, "app-token").get("/api/profile/").status_code == 401


def test_cookie_only_routes_refuse_bearer(raw_client: TestClient):
    @app.get("/api/_probe")
    def probe(cookie: CookieSession = Depends(require_cookie_session)) -> dict:
        return {"user": str(cookie.user.id), "token": cookie.access_token == "good"}

    try:
        bearer = {"Authorization": "Bearer good"}
        assert raw_client.get("/api/_probe", headers=bearer).status_code == 401
        assert raw_client.get("/api/_probe").status_code == 401
        client = signed_in(raw_client)
        assert client.get("/api/_probe").json() == {"user": str(TEST_USER_ID), "token": True}
        assert client.get("/api/_probe", headers=bearer).status_code == 401
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/api/_probe"]


def preflight(origin: str) -> dict:
    tiny = FastAPI()

    @tiny.get("/x")
    def x() -> dict:
        return {}

    tiny.add_middleware(CORSMiddleware, **cors_options())
    headers = {"Origin": origin, "Access-Control-Request-Method": "PATCH"}
    return dict(TestClient(tiny).options("/x", headers=headers).headers)


def test_cors_allows_only_the_frontend(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "frontend_origin", FRONTEND)
    allowed = preflight(FRONTEND)
    assert allowed["access-control-allow-origin"] == FRONTEND
    assert allowed["access-control-allow-credentials"] == "true"
    assert "access-control-allow-origin" not in preflight("https://evil.example")
    monkeypatch.setattr(settings, "frontend_origin", None)
    assert "access-control-allow-origin" not in preflight(FRONTEND)


def test_the_app_has_cors():
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)


def test_one_request_refreshes_the_session_once(raw_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Supabase rotates refresh tokens: a second refresh in the same request would spend the old one again. A cookie-only
    route also runs the router's own sign-in check, and both must share one refresh."""
    calls = []

    def refresh(token: str) -> SessionTokens:
        calls.append(token)
        return SessionTokens("good", "new-refresh", 3600)

    monkeypatch.setattr(auth, "refresh_session", refresh)
    raw_client.cookies.set(ACCESS_COOKIE, "expired", path="/")
    raw_client.cookies.set(REFRESH_COOKIE, "r", path="/")
    assert raw_client.get("/api/data-options").status_code == 200
    assert calls == ["r"]


# What a token alone must never do, with real authentication (the shared test client switches the guard off).
COOKIE_ONLY = [
    ("/api/erase", {"confirm": "nope"}),
    ("/api/delete-account", {"confirm": "nope"}),
    ("/api/assistants/tokens", {"name": "x"}),
    ("/api/oauth/consent/some-id", {"decision": "deny"}),
]


@pytest.mark.parametrize(("path", "body"), COOKIE_ONLY)
def test_cookie_only_routes_need_the_app_and_refuse_bearer(raw_client: TestClient, path: str, body: dict):
    bearer = {"Authorization": "Bearer good"}
    assert raw_client.post(path, json=body, headers={**bearer, **APP}).status_code == 401
    client = signed_in(raw_client)
    assert client.post(path, json=body).status_code == 403, "a cookie without the app's header and origin"
    assert client.post(path, json=body, headers={**bearer, **APP}).status_code == 401, "bearer beside a cookie"


def test_cookie_only_routes_answer_the_app(raw_client: TestClient):
    client = signed_in(raw_client)
    assert client.post("/api/erase", json={"confirm": "test@example.com"}, headers=APP).status_code == 204
    assert client.post("/api/assistants/tokens", json={"name": "x"}, headers=APP).status_code == 201


def test_the_frontend_origin_setting_forgives_a_trailing_slash():
    from app.config import Settings

    assert Settings(frontend_origin="https://app.example.com/").frontend_origin == "https://app.example.com"
    assert Settings(frontend_origin="").frontend_origin is None
