"""The app reaches /api with its session cookie: reads freely, changes only from the address the request came in on,
with the X-Finode header. A bearer token still works as before, and cookie-only routes refuse it."""

from collections.abc import Generator

import pytest
from fastapi import Depends, HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session

from finode.auth import identity as auth
from finode.auth.identity import CookieSession, require_cookie_session
from finode.auth.session import ACCESS_COOKIE, REFRESH_COOKIE, SessionTokens
from finode.dependencies import get_db_session
from finode.main import app
from tests.conftest import TEST_USER_ID

APP = {"X-Finode": "1", "Origin": "http://testserver"}


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


def test_an_entry_says_whether_the_app_or_a_script_made_it(client, root_accounts):
    """The app signs in with its cookie session and records "web" (the app); a request with its own bearer token is a
    script and records "api" (step 10: every write now comes through /api, so the path no longer tells them apart)."""
    from tests.books import leg, post_account

    bank = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "10"}).json()
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()
    body = {"postings": [leg(food, "debit", "1"), leg(bank, "credit", "1")]}
    assert client.post("/api/transactions/", json=body).json()["created_via"] == "web"
    scripted = client.post("/api/transactions/", json=body, headers={"Authorization": "Bearer some-supabase-jwt"})
    assert scripted.status_code == 201 and scripted.json()["created_via"] == "api"


# ---- one address (step 10): the app and the API share an origin; a cookie write must come from it ---------------------


def test_a_cookie_write_from_the_requests_own_origin_passes_and_any_other_is_refused(raw_client: TestClient):
    client = signed_in(raw_client)
    change = {"first_name": "A"}
    own = {"X-Finode": "1", "Origin": "http://testserver"}
    assert client.patch("/api/profile/", json=change, headers=own).status_code == 200
    for other in ("https://evil.example", "https://app.example.com", "http://testserver.evil.example"):
        refused = client.patch("/api/profile/", json=change, headers={"X-Finode": "1", "Origin": other})
        assert refused.status_code == 403, other
    assert client.patch("/api/profile/", json=change, headers={"X-Finode": "1"}).status_code == 403, "no origin"
    assert client.patch("/api/profile/", json=change, headers={"Origin": "http://testserver"}).status_code == 403


def test_the_origin_is_the_scheme_and_host_the_request_came_in_on(session, monkeypatch: pytest.MonkeyPatch):
    """Behind Traefik, uvicorn (--proxy-headers) gives the request its https scheme and public host; the origin the
    browser sends must match those exactly."""
    monkeypatch.setattr(auth, "verify_supabase_jwt", fake_verify)
    app.dependency_overrides[get_db_session] = lambda: session
    try:
        with TestClient(app, base_url="https://finode.example") as client:
            client.cookies.set(ACCESS_COOKIE, "good", path="/")
            change = {"first_name": "A"}
            same = {"X-Finode": "1", "Origin": "https://finode.example"}
            assert client.patch("/api/profile/", json=change, headers=same).status_code == 200
            plain_http = {"X-Finode": "1", "Origin": "http://finode.example"}
            assert client.patch("/api/profile/", json=change, headers=plain_http).status_code == 403
    finally:
        app.dependency_overrides.clear()
