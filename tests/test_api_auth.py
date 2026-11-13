"""/api/auth: what the finode app uses to sign people in, up and out, reset a password and learn who is signed in.
The rules and messages are the web pages' own (app/auth_flows.py)."""

from datetime import date

import pytest

from app import auth_flows
from app.config import settings
from app.reset import ResetLinkInvalidError
from app.routers import auth as auth_router
from app.session import ACCESS_COOKIE, REFRESH_COOKIE, InvalidCredentialsError, SessionTokens

FRONTEND = "https://app.example.com"
APP = {"X-Finode": "1", "Origin": FRONTEND}
TOKENS = SessionTokens("access-1", "refresh-1", 3600)
SIGN_UP = {
    "email": "new@example.com",
    "password": "correct horse",
    "confirm_password": "correct horse",
    "invite_code": "a-long-enough-invite-code",
}


@pytest.fixture(autouse=True)
def from_the_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "frontend_origin", FRONTEND)


@pytest.fixture
def signup_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "signup_code", SIGN_UP["invite_code"])
    monkeypatch.setattr(settings, "supabase_service_role_key", "sb_secret_test_key")
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(auth_flows, "create_user", lambda email, password: None)
    monkeypatch.setattr(auth_flows, "sign_in", lambda email, password: TOKENS)


@pytest.fixture
def reset_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "password_reset", True)
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")


def cookies_set(response) -> list[str]:
    return response.headers.get_list("set-cookie")


def test_options_say_what_is_offered(client):
    assert client.get("/api/auth/options").json() == {
        "signup_enabled": False,
        "reset_enabled": False,
        "test_notice": False,
    }


def test_session_gives_today_from_the_server(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_router, "local_today", lambda: date(2026, 1, 31))
    seen = client.get("/api/auth/session").json()
    assert seen["today"] == "2026-01-31" and seen["email"] == "test@example.com"
    assert seen["can_delete_login"] is False and seen["feedback_url"] is None


def test_sign_in_sets_the_cookies(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_flows, "sign_in", lambda email, password: TOKENS)
    response = client.post("/api/auth/sign-in", json={"email": "a@b.co", "password": "pw"}, headers=APP)
    assert response.status_code == 204
    cookies = cookies_set(response)
    assert any(c.startswith(f"{ACCESS_COOKIE}=access-1") and "HttpOnly" in c for c in cookies)
    assert any(c.startswith(f"{REFRESH_COOKIE}=refresh-1") and "HttpOnly" in c for c in cookies)


def wrong(email: str, password: str) -> SessionTokens:
    raise InvalidCredentialsError()


def test_wrong_password(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_flows, "sign_in", wrong)
    response = client.post("/api/auth/sign-in", json={"email": "a@b.co", "password": "bad"}, headers=APP)
    assert response.status_code == 401
    assert response.json()["detail"]["message"] == "Invalid email or password."
    assert "set-cookie" not in response.headers


def test_sign_in_is_rate_limited(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_flows, "sign_in", wrong)
    for _ in range(settings.login_attempts):
        client.post("/api/auth/sign-in", json={"email": "a@b.co", "password": "bad"}, headers=APP)
    response = client.post("/api/auth/sign-in", json={"email": "a@b.co", "password": "bad"}, headers=APP)
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0


def test_auth_posts_need_the_app_headers(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_flows, "sign_in", lambda email, password: TOKENS)
    assert client.post("/api/auth/sign-in", json={"email": "a@b.co", "password": "pw"}).status_code == 403
    assert client.post("/api/auth/sign-out").status_code == 403


def test_sign_up_is_hidden_when_off(client):
    assert client.post("/api/auth/sign-up", json=SIGN_UP, headers=APP).status_code == 404


@pytest.mark.usefixtures("signup_on")
def test_sign_up_rules(client):
    bad_code = client.post("/api/auth/sign-up", json={**SIGN_UP, "invite_code": "nope"}, headers=APP)
    assert bad_code.status_code == 403 and bad_code.json()["detail"]["message"] == "Invalid invite code."
    mismatch = client.post("/api/auth/sign-up", json={**SIGN_UP, "confirm_password": "other one"}, headers=APP)
    assert mismatch.status_code == 400 and mismatch.json()["detail"]["message"] == "Passwords do not match."
    done = client.post("/api/auth/sign-up", json=SIGN_UP, headers=APP)
    assert done.status_code == 201 and done.json() == {"signed_in": True}
    assert any(c.startswith(f"{ACCESS_COOKIE}=access-1") for c in cookies_set(done))


@pytest.mark.usefixtures("reset_on")
def test_forgot_answers_the_same_for_anyone(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_flows, "send_reset_email", lambda email: None)
    for email in ("known@example.com", "nobody@example.com"):
        assert client.post("/api/auth/forgot", json={"email": email}, headers=APP).status_code == 202


def test_forgot_and_reset_are_hidden_when_off(client):
    assert client.post("/api/auth/forgot", json={"email": "a@b.co"}, headers=APP).status_code == 404
    body = {"token_hash": "t", "password": "correct horse", "confirm_password": "correct horse"}
    assert client.post("/api/auth/reset", json=body, headers=APP).status_code == 404


@pytest.mark.usefixtures("reset_on")
def test_a_spent_reset_link(client, monkeypatch: pytest.MonkeyPatch):
    def spent(token_hash: str, password: str) -> SessionTokens:
        raise ResetLinkInvalidError()

    monkeypatch.setattr(auth_flows, "reset_password", spent)
    body = {"token_hash": "t", "password": "correct horse", "confirm_password": "correct horse"}
    response = client.post("/api/auth/reset", json=body, headers=APP)
    assert response.status_code == 400 and response.json()["detail"]["code"] == "link-invalid"


@pytest.mark.usefixtures("reset_on")
def test_a_reset_signs_in(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_flows, "reset_password", lambda token_hash, password: TOKENS)
    body = {"token_hash": "t", "password": "correct horse", "confirm_password": "correct horse"}
    response = client.post("/api/auth/reset", json=body, headers=APP)
    assert response.status_code == 204
    assert any(c.startswith(f"{ACCESS_COOKIE}=access-1") for c in cookies_set(response))


def test_sign_out_clears_the_cookies(client):
    response = client.post("/api/auth/sign-out", headers=APP)
    assert response.status_code == 204
    cookies = cookies_set(response)
    assert any(c.startswith(f"{ACCESS_COOKIE}=") and "Max-Age=0" in c for c in cookies)
    assert any(c.startswith(f"{REFRESH_COOKIE}=") and "Max-Age=0" in c for c in cookies)
