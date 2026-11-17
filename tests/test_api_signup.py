"""Sign-up through /api/auth (ported from the old sign-up page's tests, step 10): hidden until it is set up, the invite
code checked before anything reaches Supabase, the rules and Supabase's refusals said in words, a limit on how many
people may join, and no secret ever in an answer."""

from uuid import uuid4

import pytest

from app import auth_flows
from app.config import settings
from app.models.profile import Profile
from app.session import ACCESS_COOKIE, AuthUnavailableError, InvalidCredentialsError, SessionTokens
from app.signup import EmailAlreadyRegisteredError, RateLimitedError, SignupRejectedError

from .test_api_auth import APP, SIGN_UP, from_the_app  # noqa: F401  (an autouse fixture)

CODE = SIGN_UP["invite_code"]
SERVICE_KEY = "sb_secret_test_key"


@pytest.fixture
def signup_on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "signup_code", CODE)
    monkeypatch.setattr(settings, "supabase_service_role_key", SERVICE_KEY)


@pytest.fixture
def supabase(monkeypatch: pytest.MonkeyPatch):
    """Record calls to Supabase; every call succeeds unless a test overrides it."""
    calls: dict[str, list] = {"create_user": [], "sign_in": []}
    monkeypatch.setattr(auth_flows, "create_user", lambda email, password: calls["create_user"].append(email))

    def fake_sign_in(email, password):
        calls["sign_in"].append(email)
        return SessionTokens("access-1", "refresh-1", 3600)

    monkeypatch.setattr(auth_flows, "sign_in", fake_sign_in)
    return calls


def sign_up(client, **changes):
    return client.post("/api/auth/sign-up", json={**SIGN_UP, **changes}, headers=APP)


def test_sign_up_is_hidden_until_it_is_set_up(client, monkeypatch):
    assert sign_up(client).status_code == 404
    assert client.get("/api/auth/options").json()["signup_enabled"] is False
    monkeypatch.setattr(settings, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "signup_code", CODE)
    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    assert sign_up(client).status_code == 404, "without the admin key nobody can be made"


@pytest.mark.usefixtures("signup_on")
def test_signing_up_signs_the_person_in(client, supabase):
    done = sign_up(client)
    assert done.status_code == 201 and done.json() == {"signed_in": True}
    assert any(c.startswith(f"{ACCESS_COOKIE}=access-1") for c in done.headers.get_list("set-cookie"))
    assert supabase["create_user"] == ["new@example.com"] and supabase["sign_in"] == ["new@example.com"]


@pytest.mark.usefixtures("signup_on")
def test_a_wrong_invite_code_never_reaches_supabase(client, supabase):
    for code in ("", "wrong", CODE.upper()):
        refused = sign_up(client, invite_code=code)
        assert refused.status_code == 403 and refused.json()["detail"]["message"] == "Invalid invite code."
        assert "set-cookie" not in refused.headers
    assert supabase["create_user"] == []


@pytest.mark.usefixtures("signup_on")
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"email": "not-an-email"}, "valid email"),
        ({"email": ""}, "valid email"),
        ({"password": "short", "confirm_password": "short"}, "at least 8 characters"),
        ({"confirm_password": "different one"}, "do not match"),
    ],
)
def test_the_rules_are_said_in_words(client, supabase, changes, message):
    refused = sign_up(client, **changes)
    assert refused.status_code in (400, 422) and message in refused.text
    assert supabase["create_user"] == []


@pytest.mark.usefixtures("signup_on")
@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (EmailAlreadyRegisteredError(), 409, "already exists"),
        (SignupRejectedError("Password is too common."), 400, "Password is too common."),
        (RateLimitedError(), 429, "Too many attempts"),
        (AuthUnavailableError("down"), 503, "currently unavailable"),
    ],
)
def test_supabases_refusals_are_said_in_words(client, supabase, monkeypatch, error, status, message):
    def fail(email, password):
        raise error

    monkeypatch.setattr(auth_flows, "create_user", fail)
    refused = sign_up(client)
    assert refused.status_code == status and message in refused.text
    assert "set-cookie" not in refused.headers and supabase["sign_in"] == []


@pytest.mark.usefixtures("signup_on")
@pytest.mark.parametrize("error", [InvalidCredentialsError(), AuthUnavailableError("down")])
def test_when_signing_in_after_fails_the_account_is_still_made(client, supabase, monkeypatch, error):
    def fail(email, password):
        raise error

    monkeypatch.setattr(auth_flows, "sign_in", fail)
    made = sign_up(client)
    assert made.status_code == 201 and made.json() == {"signed_in": False}, "the app asks to sign in"
    assert "set-cookie" not in made.headers


@pytest.mark.usefixtures("signup_on")
def test_secrets_never_appear_in_answers(client, supabase):
    answers = [
        client.get("/api/auth/options"),
        sign_up(client, invite_code="wrong"),
        sign_up(client, confirm_password="different one"),
        sign_up(client),
    ]
    for answer in answers:
        assert CODE not in answer.text and SERVICE_KEY not in answer.text and SERVICE_KEY not in str(answer.headers)
        assert "correct horse" not in answer.text


@pytest.mark.usefixtures("signup_on")
def test_sign_up_closes_when_everyone_the_limit_allows_is_in(client, session, supabase, monkeypatch):
    monkeypatch.setattr(settings, "max_users", 2)
    session.add_all([Profile(user_id=uuid4()), Profile(user_id=uuid4())])
    session.commit()
    full = sign_up(client)
    assert full.status_code == 403 and "Registration is full" in full.text
    assert supabase["create_user"] == [], "nothing reached Supabase"
    wrong = sign_up(client, invite_code="wrong")
    assert wrong.status_code == 403 and "Invalid invite code" in wrong.text, "a wrong code is refused before the limit"
    monkeypatch.setattr(settings, "max_users", 3)
    assert sign_up(client).status_code == 201, "room for one more"
    monkeypatch.setattr(settings, "max_users", 0)
    assert sign_up(client, email="other@example.com").status_code == 201, "0 means no limit"
