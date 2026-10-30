"""What one person may hold, and how fast sign-in and sign-up attempts may come."""

import io
import json

import pytest

from app.config import settings
from app.ratelimit import AttemptLimiter
from app.routers.web import auth as web_auth_router
from app.web_auth import InvalidCredentialsError, SessionTokens

from .books import post_account
from .test_web_signup import CODE, FORM, raw_client, signup_on, supabase  # noqa: F401  (fixtures used by name)

# ---- the counter ----------------------------------------------------------------------------------------------


def test_the_limiter_counts_a_sliding_window():
    limiter = AttemptLimiter()
    for t in (0, 1, 2):
        assert limiter.retry_after("k", 3, 60, now=t) is None
        limiter.hit("k", now=t)
    assert limiter.retry_after("k", 3, 60, now=3) == 57, "the oldest attempt leaves the window at 60"
    assert limiter.retry_after("other", 3, 60, now=3) is None, "keys are separate"
    assert limiter.retry_after("k", 3, 60, now=60.5) is None, "room again once the oldest has aged out"


def test_the_limiter_can_be_reset_or_off():
    limiter = AttemptLimiter()
    for _ in range(5):
        limiter.hit("k", now=0)
    assert limiter.retry_after("k", 0, 60, now=1) is None, "0 means no limit"
    assert limiter.retry_after("k", 5, 60, now=1) is not None
    limiter.reset("k")
    assert limiter.retry_after("k", 5, 60, now=1) is None


# ---- sign-in and sign-up -------------------------------------------------------------------------------------


@pytest.fixture
def failing_sign_in(monkeypatch):
    calls = []

    def fail(email, password):
        calls.append(email)
        raise InvalidCredentialsError()

    monkeypatch.setattr(web_auth_router, "sign_in", fail)
    return calls


def test_repeated_wrong_passwords_are_slowed_down(raw_client, failing_sign_in, monkeypatch):
    monkeypatch.setattr(settings, "login_attempts", 3)
    for _ in range(3):
        assert raw_client.post("/login", data={"email": "a@x.com", "password": "bad"}).status_code == 401
    blocked = raw_client.post("/login", data={"email": "a@x.com", "password": "bad"})
    assert blocked.status_code == 429 and "Too many sign-in attempts" in blocked.text
    assert int(blocked.headers["Retry-After"]) > 0
    assert len(failing_sign_in) == 3, "the blocked attempt never reached Supabase"
    other = raw_client.post("/login", data={"email": "b@x.com", "password": "bad"})
    assert other.status_code == 429, "the same address is slowed down whatever email it tries"


def test_one_email_is_slowed_down_from_every_address(raw_client, failing_sign_in, monkeypatch):
    monkeypatch.setattr(settings, "login_attempts", 2)
    monkeypatch.setattr(web_auth_router, "_client", lambda request: request.headers["x-test-ip"])
    for ip in ("1.1.1.1", "2.2.2.2"):
        raw_client.post("/login", data={"email": "victim@x.com", "password": "bad"}, headers={"x-test-ip": ip})
    blocked = raw_client.post(
        "/login", data={"email": "victim@x.com", "password": "bad"}, headers={"x-test-ip": "3.3.3.3"}
    )
    assert blocked.status_code == 429, "guessing one person's password from many addresses is slowed too"
    assert (
        raw_client.post(
            "/login", data={"email": "someone@x.com", "password": "bad"}, headers={"x-test-ip": "3.3.3.3"}
        ).status_code
        == 401
    )


def test_a_good_sign_in_is_not_counted_and_clears_the_email(raw_client, monkeypatch):
    monkeypatch.setattr(settings, "login_attempts", 2)
    outcomes = iter([InvalidCredentialsError(), None, InvalidCredentialsError(), InvalidCredentialsError()])

    def sign_in(email, password):
        outcome = next(outcomes)
        if outcome:
            raise outcome
        return SessionTokens("a", "r", 3600)

    monkeypatch.setattr(web_auth_router, "sign_in", sign_in)
    assert raw_client.post("/login", data={"email": "a@x.com", "password": "x"}).status_code == 401
    assert raw_client.post("/login", data={"email": "a@x.com", "password": "ok"}).status_code == 303
    # the address still has one failure on record, so one more is allowed and the next is not
    assert raw_client.post("/login", data={"email": "a@x.com", "password": "x"}).status_code == 401
    assert raw_client.post("/login", data={"email": "a@x.com", "password": "x"}).status_code == 429


def test_sign_up_attempts_are_limited_even_with_the_right_code(raw_client, signup_on, supabase, monkeypatch):
    monkeypatch.setattr(settings, "signup_attempts", 2)
    assert raw_client.post("/signup", data={**FORM, "invite_code": "wrong"}).status_code == 403
    assert raw_client.post("/signup", data={**FORM, "invite_code": "wrong"}).status_code == 403
    blocked = raw_client.post("/signup", data=FORM)
    assert blocked.status_code == 429 and "Too many attempts" in blocked.text and "Retry-After" in blocked.headers
    assert supabase["create_user"] == [], "nothing reached Supabase"


# ---- what one person may hold -----------------------------------------------------------------------------


def test_accounts_are_limited(client, root_accounts, monkeypatch):
    count = len(client.get("/api/accounts/").json())
    monkeypatch.setattr(settings, "max_accounts", count + 1)
    assert post_account(client, {"name": "One", "parent_id": root_accounts["Assets"]}).status_code == 201
    refused = post_account(client, {"name": "Two", "parent_id": root_accounts["Assets"]})
    assert refused.status_code == 400 and f"limit of {count + 1} accounts" in refused.json()["detail"]
    form = client.post("/accounts", data={"name": "Three", "parent_id": root_accounts["Assets"]})
    assert "limit of" in form.text
    monkeypatch.setattr(settings, "max_accounts", 0)
    assert post_account(client, {"name": "Two", "parent_id": root_accounts["Assets"]}).status_code == 201, (
        "0 = no limit"
    )


def make_tx(client, a, b, amount="1"):
    return client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": a["aid"], "side": "debit", "amount": amount},
                {"account": b["aid"], "side": "credit", "amount": amount},
            ]
        },
    )


@pytest.fixture
def two_accounts(client, root_accounts):
    a = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"]}).json()
    b = post_account(client, {"name": "Shop", "parent_id": root_accounts["Expenses"]}).json()
    return a, b


def test_transactions_are_limited_in_total(client, two_accounts, monkeypatch):
    a, b = two_accounts
    monkeypatch.setattr(settings, "max_transactions", 2)
    assert make_tx(client, b, a).status_code == 201 and make_tx(client, b, a).status_code == 201
    refused = make_tx(client, b, a)
    assert refused.status_code == 400 and "limit of 2 transactions" in refused.json()["detail"]


def test_new_transactions_a_day_are_limited_but_not_recurring_ones(client, two_accounts, monkeypatch):
    a, b = two_accounts
    monkeypatch.setattr(settings, "max_transactions_per_day", 2)
    assert make_tx(client, b, a).status_code == 201 and make_tx(client, b, a).status_code == 201
    refused = make_tx(client, b, a)
    assert refused.status_code == 400 and "new transactions a day" in refused.json()["detail"]
    rule = client.post(
        "/api/recurring/",
        json={
            "from_account": a["aid"],
            "to_account": b["aid"],
            "amount": "1",
            "frequency": "daily",
            "start_date": "2026-09-01",
        },
    )
    assert rule.status_code == 201
    made = [t for t in client.get("/api/transactions/").json() if t.get("created_via") == "recurring"]
    assert len(made) > 5, "a rule catching up is not a person typing"


def test_a_transaction_cannot_have_endless_rows(client, two_accounts, monkeypatch):
    a, b = two_accounts
    monkeypatch.setattr(settings, "max_postings_per_transaction", 3)
    rows = [{"account": b["aid"], "side": "debit", "amount": "1"} for _ in range(3)] + [
        {"account": a["aid"], "side": "credit", "amount": "3"}
    ]
    refused = client.post("/api/transactions/", json={"postings": rows})
    assert refused.status_code == 400 and "at most 3 postings" in refused.json()["detail"]


def test_an_import_that_would_pass_the_limits_is_refused_with_a_reason(client, root_accounts, monkeypatch):
    journal = "2026-01-01 Shop\n    Expenses:Food    5\n    Assets:Bank\n"
    monkeypatch.setattr(settings, "max_accounts", 6)
    preview = client.post("/api/import", params={"dry_run": True}, files={"file": ("j.ledger", journal, "text/plain")})
    assert preview.status_code == 200 and any("too big for your limits" in e for e in preview.json()["errors"])
    refused = client.post("/api/import", files={"file": ("j.ledger", journal, "text/plain")})
    assert refused.status_code == 400
    monkeypatch.setattr(settings, "max_accounts", 500)
    assert client.post("/api/import", files={"file": ("j.ledger", journal, "text/plain")}).status_code == 200


def test_a_backup_bigger_than_the_limits_is_refused(client, session, root_accounts, monkeypatch):
    from uuid import UUID

    from app.auth import CurrentUser, require_authenticated_user
    from app.main import app

    from .test_backup import acct

    acct(client, "Bank", root_accounts["Assets"], balance="5")
    doc = client.get("/api/backup").json()
    app.dependency_overrides[require_authenticated_user] = lambda: CurrentUser(
        id=UUID(int=99), email="n@x.com", claims={}
    )
    monkeypatch.setattr(settings, "max_accounts", 2)
    refused = client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")})
    assert refused.status_code == 400 and "bigger than your limits allow" in str(refused.json())
    monkeypatch.setattr(settings, "max_accounts", 500)
    assert (
        client.post("/api/restore", files={"file": ("b.json", json.dumps(doc), "application/json")}).status_code == 200
    )


def test_uploads_have_a_size_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_restore_mb", 1)
    big = io.BytesIO(b" " * (1024 * 1024 + 10))
    response = client.post("/api/restore", files={"file": ("b.json", big, "application/json")})
    assert response.status_code == 400 and "larger than 1 MB" in str(response.json())
    over = io.BytesIO(b"x" * (5 * 1024 * 1024 + 10))
    assert "larger than 5 MB" in client.post("/api/import", files={"file": ("j.ledger", over, "text/plain")}).text
