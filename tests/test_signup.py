import httpx
import pytest

from app import signup
from app.config import Settings, settings
from app.signup import (
    EmailAlreadyRegisteredError,
    RateLimitedError,
    SignupRejectedError,
    create_user,
    invite_code_is_valid,
)
from app.web_auth import AuthUnavailableError


CODE = "a-long-enough-invite-code"
SERVICE_KEY = "sb_secret_test_key"


@pytest.fixture
def signup_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "signup_code", CODE)
    monkeypatch.setattr(settings, "supabase_service_role_key", SERVICE_KEY)


def _respond(monkeypatch: pytest.MonkeyPatch, status: int, body: dict | None = None):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        return httpx.Response(status, json=body if body is not None else {})

    monkeypatch.setattr(signup.httpx, "post", fake_post)
    return calls


def test_signup_enabled_requires_code_service_key_and_url():
    assert Settings(_env_file=None).signup_enabled is False
    assert Settings(_env_file=None, signup_code=CODE).signup_enabled is False
    assert Settings(
        _env_file=None, signup_code=CODE, supabase_service_role_key="k"
    ).signup_enabled is False
    assert Settings(
        _env_file=None,
        signup_code=CODE,
        supabase_service_role_key="k",
        supabase_url="https://proj.supabase.co",
    ).signup_enabled is True


def test_short_signup_code_is_rejected_and_blank_means_disabled():
    with pytest.raises(ValueError, match="at least 16 characters"):
        Settings(_env_file=None, signup_code="too-short")
    assert Settings(_env_file=None, signup_code="").signup_code is None


def test_invite_code_comparison(signup_configured):
    assert invite_code_is_valid(CODE) is True
    assert invite_code_is_valid(CODE + "x") is False
    assert invite_code_is_valid("") is False
    assert invite_code_is_valid("é" * 40) is False


def test_invite_code_never_valid_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "signup_code", None)
    assert invite_code_is_valid("") is False
    assert invite_code_is_valid("anything") is False


def test_create_user_sends_confirmed_user_to_admin_api(signup_configured, monkeypatch):
    calls = _respond(monkeypatch, 200, {"id": "x"})
    create_user("new@example.com", "s3cret-pass")

    [call] = calls
    assert call["url"] == "https://proj.supabase.co/auth/v1/admin/users"
    assert call["json"] == {
        "email": "new@example.com",
        "password": "s3cret-pass",
        "email_confirm": True,
    }
    assert call["headers"] == {"apikey": SERVICE_KEY}


def test_create_user_sends_legacy_jwt_key_as_bearer_too(signup_configured, monkeypatch):
    monkeypatch.setattr(settings, "supabase_service_role_key", "eyJhbGciOi.payload.sig")
    calls = _respond(monkeypatch, 200)
    create_user("new@example.com", "s3cret-pass")
    assert calls[0]["headers"]["Authorization"] == "Bearer eyJhbGciOi.payload.sig"


def test_create_user_duplicate_email(signup_configured, monkeypatch):
    _respond(monkeypatch, 422, {"error_code": "email_exists", "msg": "already registered"})
    with pytest.raises(EmailAlreadyRegisteredError):
        create_user("dup@example.com", "s3cret-pass")


def test_create_user_surfaces_supabase_validation_messages(signup_configured, monkeypatch):
    _respond(
        monkeypatch,
        422,
        {"error_code": "weak_password", "msg": "Password should be at least 6 characters."},
    )
    with pytest.raises(SignupRejectedError, match="at least 6 characters"):
        create_user("new@example.com", "x")


def test_create_user_rate_limited(signup_configured, monkeypatch):
    _respond(monkeypatch, 429, {"msg": "slow down"})
    with pytest.raises(RateLimitedError):
        create_user("new@example.com", "s3cret-pass")


@pytest.mark.parametrize("status", [401, 403, 500, 502])
def test_create_user_hides_misconfiguration_and_outages(signup_configured, monkeypatch, status):
    _respond(monkeypatch, status, {"msg": "Invalid API key"})
    with pytest.raises(AuthUnavailableError):
        create_user("new@example.com", "s3cret-pass")


def test_create_user_network_failure(signup_configured, monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(signup.httpx, "post", boom)
    with pytest.raises(AuthUnavailableError):
        create_user("new@example.com", "s3cret-pass")


def test_create_user_refuses_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "signup_code", None)
    calls = _respond(monkeypatch, 200)
    with pytest.raises(AuthUnavailableError):
        create_user("new@example.com", "s3cret-pass")
    assert calls == []
