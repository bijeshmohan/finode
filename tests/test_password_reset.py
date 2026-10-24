import httpx
import pytest

from app import reset
from app.config import Settings, settings
from app.web_auth import ACCESS_COOKIE, AuthUnavailableError

from .test_web_signup import raw_client  # noqa: F401

TOKENS = {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}


@pytest.fixture
def reset_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_anon_key", "anon-key")
    monkeypatch.setattr(settings, "password_reset", True)


class Supabase:
    def __init__(self, monkeypatch):
        self.calls = []
        self.recover = 200
        self.verify = (200, TOKENS)
        self.update = (200, {})
        monkeypatch.setattr(reset.httpx, "post", self._post)
        monkeypatch.setattr(reset.httpx, "put", self._put)

    def _post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, headers))
        if url.endswith("/recover"):
            return httpx.Response(self.recover, json={})
        return httpx.Response(self.verify[0], json=self.verify[1])

    def _put(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("PUT", url, json, headers))
        return httpx.Response(self.update[0], json=self.update[1])


@pytest.fixture
def supabase(monkeypatch):
    return Supabase(monkeypatch)


def test_reset_is_off_until_configured(raw_client):
    assert Settings(_env_file=None).reset_enabled is False
    assert raw_client.get("/forgot").status_code == 404
    assert raw_client.post("/forgot", data={"email": "a@b.co"}).status_code == 404
    assert raw_client.get("/reset?token_hash=x").status_code == 404
    assert "Forgot" not in raw_client.get("/login").text


def test_login_page_links_to_it_when_on(raw_client, reset_on):
    assert "/forgot" in raw_client.get("/login").text


def test_asking_for_a_link_gives_the_same_answer_for_any_address(raw_client, reset_on, supabase):
    r = raw_client.post("/forgot", data={"email": "someone@example.com"})
    assert r.status_code == 200 and "on its way" in r.text
    assert supabase.calls[0][1] == "https://proj.supabase.co/auth/v1/recover"
    assert supabase.calls[0][2] == {"email": "someone@example.com"}
    assert supabase.calls[0][3]["apikey"] == "anon-key"
    supabase.recover = 429  # Supabase's own once-a-minute limit looks the same to the visitor
    r = raw_client.post("/forgot", data={"email": "other@example.com"})
    assert r.status_code == 200 and "on its way" in r.text


def test_asking_checks_the_address_and_survives_an_outage(raw_client, reset_on, supabase):
    assert raw_client.post("/forgot", data={"email": "nope"}).status_code == 400
    supabase.recover = 500
    r = raw_client.post("/forgot", data={"email": "a@b.co"})
    assert r.status_code == 503 and "Could not send" in r.text


def test_asking_is_rate_limited_per_address_and_per_visitor(raw_client, reset_on, supabase, monkeypatch):
    monkeypatch.setattr(settings, "reset_attempts", 2)
    for _ in range(2):
        assert raw_client.post("/forgot", data={"email": "a@b.co"}).status_code == 200
    r = raw_client.post("/forgot", data={"email": "a@b.co"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert len([c for c in supabase.calls if c[1].endswith("/recover")]) == 2  # nothing more reached Supabase


def test_opening_the_link_only_shows_a_form(raw_client, reset_on, supabase):
    r = raw_client.get("/reset?token_hash=abc123")
    assert r.status_code == 200 and 'value="abc123"' in r.text
    assert supabase.calls == []  # a mail scanner opening the link must not spend the token
    assert raw_client.get("/reset").status_code == 400


def test_choosing_a_password_spends_the_token_and_signs_in(raw_client, reset_on, supabase):
    r = raw_client.post(
        "/reset", data={"token_hash": "abc123", "password": "a-new-password", "confirm_password": "a-new-password"}
    )
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert r.cookies.get(ACCESS_COOKIE) == "new-access"
    verify, update = supabase.calls
    assert verify[1].endswith("/verify") and verify[2] == {"type": "recovery", "token_hash": "abc123"}
    assert update[0] == "PUT" and update[1].endswith("/user") and update[2] == {"password": "a-new-password"}
    assert update[3]["Authorization"] == "Bearer new-access"


def test_a_short_or_mismatched_password_does_not_spend_the_token(raw_client, reset_on, supabase):
    r = raw_client.post("/reset", data={"token_hash": "t", "password": "short", "confirm_password": "short"})
    assert r.status_code == 400 and "at least 8" in r.text and 'value="t"' in r.text
    r = raw_client.post(
        "/reset", data={"token_hash": "t", "password": "long-enough-1", "confirm_password": "long-enough-2"}
    )
    assert r.status_code == 400 and "do not match" in r.text
    assert supabase.calls == []


def test_an_expired_or_used_link_asks_for_a_new_one(raw_client, reset_on, supabase):
    supabase.verify = (403, {"msg": "Email link is invalid or has expired"})
    r = raw_client.post(
        "/reset", data={"token_hash": "old", "password": "a-new-password", "confirm_password": "a-new-password"}
    )
    assert r.status_code == 400 and "expired or was already used" in r.text and 'action="/forgot"' in r.text
    assert len(supabase.calls) == 1  # no password change was attempted
    assert ACCESS_COOKIE not in r.cookies


def test_supabase_can_refuse_the_new_password(raw_client, reset_on, supabase):
    supabase.update = (422, {"msg": "New password should be different from the old password."})
    r = raw_client.post(
        "/reset", data={"token_hash": "t", "password": "same-as-before", "confirm_password": "same-as-before"}
    )
    assert r.status_code == 400 and "different from the old password" in r.text and 'value="t"' in r.text
    assert ACCESS_COOKIE not in r.cookies


def test_an_outage_is_reported_without_signing_anyone_in(raw_client, reset_on, supabase):
    supabase.verify = (500, {})
    r = raw_client.post(
        "/reset", data={"token_hash": "t", "password": "a-new-password", "confirm_password": "a-new-password"}
    )
    assert r.status_code == 503 and ACCESS_COOKIE not in r.cookies


def test_link_attempts_are_limited(raw_client, reset_on, supabase, monkeypatch):
    monkeypatch.setattr(settings, "reset_attempts", 1)
    supabase.verify = (403, {})
    for _ in range(2):
        raw_client.post(
            "/reset", data={"token_hash": "x", "password": "a-new-password", "confirm_password": "a-new-password"}
        )
    r = raw_client.post(
        "/reset", data={"token_hash": "x", "password": "a-new-password", "confirm_password": "a-new-password"}
    )
    assert r.status_code == 429
    assert len(supabase.calls) == 2


def test_reset_functions_refuse_when_off():
    with pytest.raises(AuthUnavailableError):
        reset.send_reset_email("a@b.co")
    with pytest.raises(AuthUnavailableError):
        reset.reset_password("t", "a-new-password")
