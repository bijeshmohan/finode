import httpx
import pytest

from app import reset
from app.config import Settings, settings
from app.session import ACCESS_COOKIE

from .test_api_auth import APP, from_the_app  # noqa: F401  (an autouse fixture)

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


def forgot(client, email):
    return client.post("/api/auth/forgot", json={"email": email}, headers=APP)


def choose(client, token_hash="t", password="a-new-password", confirm=None):
    body = {"token_hash": token_hash, "password": password, "confirm_password": confirm or password}
    return client.post("/api/auth/reset", json=body, headers=APP)


def test_reset_is_off_until_configured(client):
    assert Settings(_env_file=None).reset_enabled is False
    assert forgot(client, "a@b.co").status_code == 404 and choose(client).status_code == 404
    assert client.get("/api/auth/options").json()["reset_enabled"] is False


def test_asking_for_a_link_gives_the_same_answer_for_any_address(client, reset_on, supabase):
    assert forgot(client, "someone@example.com").status_code == 202
    assert supabase.calls[0][1] == "https://proj.supabase.co/auth/v1/recover"
    assert supabase.calls[0][2] == {"email": "someone@example.com"}
    assert supabase.calls[0][3]["apikey"] == "anon-key"
    supabase.recover = 429  # Supabase's own once-a-minute limit looks the same to the visitor
    assert forgot(client, "other@example.com").status_code == 202


def test_asking_checks_the_address_and_survives_an_outage(client, reset_on, supabase):
    assert forgot(client, "nope").status_code in (400, 422)
    supabase.recover = 500
    down = forgot(client, "a@b.co")
    assert down.status_code == 503 and "Could not send" in down.text


def test_asking_is_rate_limited_per_address_and_per_visitor(client, reset_on, supabase, monkeypatch):
    monkeypatch.setattr(settings, "reset_attempts", 2)
    for _ in range(2):
        assert forgot(client, "a@b.co").status_code == 202
    blocked = forgot(client, "a@b.co")
    assert blocked.status_code == 429 and "Retry-After" in blocked.headers
    assert len([c for c in supabase.calls if c[1].endswith("/recover")]) == 2  # nothing more reached Supabase


def test_choosing_a_password_spends_the_token_and_signs_in(client, reset_on, supabase):
    done = choose(client, "abc123")
    assert done.status_code == 204 and done.cookies.get(ACCESS_COOKIE) == "new-access"
    verify, update = supabase.calls
    assert verify[1].endswith("/verify") and verify[2] == {"type": "recovery", "token_hash": "abc123"}
    assert update[0] == "PUT" and update[1].endswith("/user") and update[2] == {"password": "a-new-password"}
    assert update[3]["Authorization"] == "Bearer new-access"


def test_a_short_or_mismatched_password_does_not_spend_the_token(client, reset_on, supabase):
    short = choose(client, password="short")
    assert short.status_code in (400, 422) and "at least 8" in short.text
    mismatched = choose(client, password="long-enough-1", confirm="long-enough-2")
    assert mismatched.status_code in (400, 422) and "do not match" in mismatched.text
    assert supabase.calls == []


def test_an_expired_or_used_link_asks_for_a_new_one(client, reset_on, supabase):
    supabase.verify = (403, {"msg": "Email link is invalid or has expired"})
    old = choose(client, "old")
    assert old.status_code == 400 and old.json()["detail"]["code"] == "link-invalid"
    assert "expired or was already used" in old.text
    assert len(supabase.calls) == 1 and ACCESS_COOKIE not in old.cookies  # no password change was attempted


def test_supabase_can_refuse_the_new_password(client, reset_on, supabase):
    supabase.update = (422, {"msg": "New password should be different from the old password."})
    refused = choose(client, password="same-as-before")
    assert refused.status_code == 400 and "different from the old password" in refused.text
    assert ACCESS_COOKIE not in refused.cookies


def test_an_outage_is_reported_without_signing_anyone_in(client, reset_on, supabase):
    supabase.verify = (500, {})
    down = choose(client)
    assert down.status_code == 503 and ACCESS_COOKIE not in down.cookies


def test_link_attempts_are_limited(client, reset_on, supabase, monkeypatch):
    monkeypatch.setattr(settings, "reset_attempts", 1)
    supabase.verify = (403, {})
    for _ in range(2):
        choose(client, "x")
    assert choose(client, "x").status_code == 429
    assert len(supabase.calls) == 2
