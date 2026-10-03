from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.config import settings
from app.dependencies import get_db_session
from app.main import app
from app.routers.web import auth as web_auth_router
from app.signup import (
    EmailAlreadyRegisteredError,
    RateLimitedError,
    SignupRejectedError,
)
from app.web_auth import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    AuthUnavailableError,
    InvalidCredentialsError,
    SessionTokens,
)


CODE = "a-long-enough-invite-code"
SERVICE_KEY = "sb_secret_test_key"
FORM = {
    "email": "new@example.com",
    "password": "correct horse",
    "confirm_password": "correct horse",
    "invite_code": CODE,
}


@pytest.fixture
def raw_client(session: Session) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_db_session] = lambda: session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def signup_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "signup_code", CODE)
    monkeypatch.setattr(settings, "supabase_service_role_key", SERVICE_KEY)


@pytest.fixture
def supabase(monkeypatch: pytest.MonkeyPatch):
    """Record calls to Supabase; every call succeeds unless a test overrides it."""
    calls = {"create_user": [], "sign_in": []}
    monkeypatch.setattr(
        web_auth_router, "create_user", lambda email, password: calls["create_user"].append(email)
    )

    def fake_sign_in(email, password):
        calls["sign_in"].append(email)
        return SessionTokens("access-1", "refresh-1", 3600)

    monkeypatch.setattr(web_auth_router, "sign_in", fake_sign_in)
    return calls


def test_signup_is_hidden_when_not_configured(raw_client: TestClient):
    assert raw_client.get("/app/signup").status_code == 404
    assert raw_client.post("/app/signup", data=FORM).status_code == 404
    assert "/app/signup" not in raw_client.get("/app/login").text


def test_signup_is_hidden_without_the_admin_key(raw_client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "signup_code", CODE)
    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    assert raw_client.get("/app/signup").status_code == 404


def test_signup_page_and_login_link_when_enabled(raw_client: TestClient, signup_on):
    page = raw_client.get("/app/signup")
    assert page.status_code == 200
    assert 'name="invite_code"' in page.text
    assert 'href="/app/signup"' in raw_client.get("/app/login").text


def test_signup_success_signs_the_user_in(raw_client: TestClient, signup_on, supabase):
    response = raw_client.post("/app/signup", data=FORM)
    assert response.status_code == 303
    assert response.headers["location"] == "/app/"
    cookies = response.headers.get_list("set-cookie")
    assert any(c.startswith(f"{ACCESS_COOKIE}=access-1") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith(f"{REFRESH_COOKIE}=refresh-1") for c in cookies)
    assert supabase["create_user"] == ["new@example.com"]
    assert supabase["sign_in"] == ["new@example.com"]


def test_wrong_invite_code_never_reaches_supabase(raw_client: TestClient, signup_on, supabase):
    for code in ("", "wrong", CODE.upper()):
        response = raw_client.post("/app/signup", data={**FORM, "invite_code": code})
        assert response.status_code == 403
        assert "Invalid invite code." in response.text
        assert "set-cookie" not in response.headers
    assert supabase["create_user"] == []


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"email": "not-an-email"}, "valid email"),
        ({"email": ""}, "valid email"),
        ({"password": "short", "confirm_password": "short"}, "at least 8 characters"),
        ({"confirm_password": "different one"}, "do not match"),
    ],
)
def test_signup_validation_errors(raw_client: TestClient, signup_on, supabase, changes, message):
    response = raw_client.post("/app/signup", data={**FORM, **changes})
    assert response.status_code == 400
    assert message in response.text
    assert supabase["create_user"] == []


def test_failed_signup_keeps_email_but_not_secrets(raw_client: TestClient, signup_on, supabase):
    response = raw_client.post("/app/signup", data={**FORM, "confirm_password": "different one"})
    assert 'value="new@example.com"' in response.text
    assert "correct horse" not in response.text
    assert CODE not in response.text


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (EmailAlreadyRegisteredError(), 409, "already exists"),
        (SignupRejectedError("Password is too common."), 400, "Password is too common."),
        (RateLimitedError(), 429, "Too many attempts"),
        (AuthUnavailableError("down"), 503, "currently unavailable"),
    ],
)
def test_signup_supabase_failures(
    raw_client: TestClient, signup_on, supabase, monkeypatch, error, status, message
):
    def fail(email, password):
        raise error

    monkeypatch.setattr(web_auth_router, "create_user", fail)
    response = raw_client.post("/app/signup", data=FORM)
    assert response.status_code == status
    assert message in response.text
    assert "set-cookie" not in response.headers
    assert supabase["sign_in"] == []


@pytest.mark.parametrize("error", [InvalidCredentialsError(), AuthUnavailableError("down")])
def test_signup_falls_back_to_login_when_auto_sign_in_fails(
    raw_client: TestClient, signup_on, supabase, monkeypatch, error
):
    def fail(email, password):
        raise error

    monkeypatch.setattr(web_auth_router, "sign_in", fail)
    response = raw_client.post("/app/signup", data=FORM)
    assert response.status_code == 303
    assert response.headers["location"] == "/app/login?created=1"
    assert "set-cookie" not in response.headers

    login = raw_client.get("/app/login", params={"created": "1"})
    assert "Account created. Please sign in." in login.text


def test_secrets_never_appear_in_responses(raw_client: TestClient, signup_on, supabase):
    pages = [
        raw_client.get("/app/signup"),
        raw_client.get("/app/login"),
        raw_client.post("/app/signup", data={**FORM, "invite_code": "wrong"}),
        raw_client.post("/app/signup", data=FORM),
    ]
    for page in pages:
        assert CODE not in page.text
        assert SERVICE_KEY not in page.text
        assert SERVICE_KEY not in str(page.headers)


def test_missing_form_fields_do_not_echo_input(raw_client: TestClient, signup_on, supabase):
    response = raw_client.post("/app/signup", data={"password": "hunter2hunter2"})
    assert response.status_code == 403
    assert "hunter2hunter2" not in response.text
