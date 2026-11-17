"""The test notice (FINODE_TEST_NOTICE) and the feedback link (FINODE_FEEDBACK_EMAIL), as the app reads them from
/api/auth (ported from the old sign-up and Settings pages' tests, step 10)."""

from urllib.parse import parse_qs, urlparse

import pytest

from finode.config import settings
from finode.version import VERSION
from tests.auth.test_api_auth import APP, SIGN_UP, signup_on  # noqa: F401  (a fixture)
from tests.auth.test_api_signup import supabase  # noqa: F401  (a fixture)


@pytest.mark.usefixtures("signup_on")
def test_without_the_test_notice_sign_up_is_as_before(client, supabase, monkeypatch):
    monkeypatch.setattr(settings, "test_notice", False)
    assert client.get("/api/auth/options").json()["test_notice"] is False
    assert client.post("/api/auth/sign-up", json=SIGN_UP, headers=APP).status_code == 201


@pytest.mark.usefixtures("signup_on")
def test_sign_up_shows_the_notice_and_wants_it_accepted(client, supabase, monkeypatch):
    monkeypatch.setattr(settings, "test_notice", True)
    assert client.get("/api/auth/options").json()["test_notice"] is True, "the app shows the notice's words"
    refused = client.post("/api/auth/sign-up", json=SIGN_UP, headers=APP)
    assert refused.status_code == 400 and "tick the box" in refused.text
    assert supabase["create_user"] == [], "no account without accepting"
    accepted = client.post("/api/auth/sign-up", json={**SIGN_UP, "accept": True}, headers=APP)
    assert accepted.status_code == 201 and supabase["create_user"] == [SIGN_UP["email"]]


def test_the_feedback_link_names_the_version_and_nothing_personal(client, monkeypatch):
    monkeypatch.setattr(settings, "feedback_email", "owner@example.com")
    link = client.get("/api/auth/session").json()["feedback_url"]
    parsed = urlparse(link)
    assert parsed.scheme == "mailto" and parsed.path == "owner@example.com"
    query = parse_qs(parsed.query)
    assert query["subject"] == ["finode feedback"] and f"finode {VERSION}" in query["body"][0]
    assert "test@example.com" not in link, "no personal data in the link"


def test_without_settings_there_is_no_feedback_link(client, monkeypatch):
    monkeypatch.setattr(settings, "feedback_email", None)
    assert client.get("/api/auth/session").json()["feedback_url"] is None
