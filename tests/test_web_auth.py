from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import auth, web_auth
from app.dependencies import get_db_session
from app.main import app
from app.web_auth import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    AuthUnavailableError,
    InvalidCredentialsError,
    SessionTokens,
)


@pytest.fixture
def raw_client(session: Session) -> Generator[TestClient, None, None]:
    """A client with real authentication; only the database is replaced."""
    app.dependency_overrides[get_db_session] = lambda: session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def valid_jwt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        auth,
        "verify_supabase_jwt",
        lambda token: {"sub": "00000000-0000-4000-8000-000000000001"}
        if token == "good-token"
        else (_ for _ in ()).throw(auth.HTTPException(status_code=401, detail="invalid")),
    )


def test_protected_page_redirects_to_login(raw_client: TestClient):
    response = raw_client.get("/")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_protected_htmx_request_gets_hx_redirect(raw_client: TestClient):
    response = raw_client.get("/", headers={"HX-Request": "true"})
    assert response.status_code == 401
    assert response.headers["HX-Redirect"] == "/login"


def test_login_page_renders(raw_client: TestClient):
    response = raw_client.get("/login")
    assert response.status_code == 200
    assert 'name="password"' in response.text


def test_login_success_sets_cookies(raw_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from app.routers.web import auth as web_auth_router

    monkeypatch.setattr(
        web_auth_router,
        "sign_in",
        lambda email, password: SessionTokens("good-token", "refresh-1", 3600),
    )

    response = raw_client.post("/login", data={"email": "a@b.co", "password": "pw"})
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith(f"{ACCESS_COOKIE}=good-token") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith(f"{REFRESH_COOKIE}=refresh-1") for c in cookies)


def test_login_invalid_credentials(raw_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from app.routers.web import auth as web_auth_router

    def fail(email, password):
        raise InvalidCredentialsError()

    monkeypatch.setattr(web_auth_router, "sign_in", fail)
    response = raw_client.post("/login", data={"email": "a@b.co", "password": "bad"})
    assert response.status_code == 401
    assert "Invalid email or password." in response.text
    assert "set-cookie" not in response.headers


def test_login_service_unavailable(raw_client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from app.routers.web import auth as web_auth_router

    def fail(email, password):
        raise AuthUnavailableError("down")

    monkeypatch.setattr(web_auth_router, "sign_in", fail)
    response = raw_client.post("/login", data={"email": "a@b.co", "password": "pw"})
    assert response.status_code == 503


def test_protected_page_with_valid_cookie(raw_client: TestClient, valid_jwt):
    raw_client.cookies.set(ACCESS_COOKIE, "good-token", path="/")
    response = raw_client.get("/")
    assert response.status_code == 200
    assert "Net worth" in response.text


def test_expired_access_token_is_refreshed(
    raw_client: TestClient, valid_jwt, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        web_auth, "refresh_session", lambda token: SessionTokens("good-token", "refresh-2", 3600)
    )
    raw_client.cookies.set(ACCESS_COOKIE, "expired-token", path="/")
    raw_client.cookies.set(REFRESH_COOKIE, "refresh-1", path="/")

    response = raw_client.get("/")
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith(f"{ACCESS_COOKIE}=good-token") for c in cookies)
    assert any(c.startswith(f"{REFRESH_COOKIE}=refresh-2") for c in cookies)


def test_failed_refresh_redirects_to_login(
    raw_client: TestClient, valid_jwt, monkeypatch: pytest.MonkeyPatch
):
    def fail(token):
        raise InvalidCredentialsError()

    monkeypatch.setattr(web_auth, "refresh_session", fail)
    raw_client.cookies.set(ACCESS_COOKIE, "expired-token", path="/")
    raw_client.cookies.set(REFRESH_COOKIE, "revoked", path="/")

    response = raw_client.get("/")
    assert response.status_code == 303


def test_logout_clears_cookies(raw_client: TestClient):
    response = raw_client.post("/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith(f"{ACCESS_COOKIE}=") and "Max-Age=0" in c for c in cookies)


def test_json_api_ignores_cookies(raw_client: TestClient, valid_jwt):
    raw_client.cookies.set(ACCESS_COOKIE, "good-token", path="/")
    response = raw_client.get("/api/accounts/")
    assert response.status_code == 401


def test_static_assets_are_served(raw_client: TestClient):
    assert raw_client.get("/static/htmx.min.js").status_code == 200
    assert raw_client.get("/static/style.css").status_code == 200
