"""The notice people accept when they join a test, the feedback link, and the first-run notes."""

from urllib.parse import parse_qs, urlparse

from app.config import settings
from app.version import VERSION

from .test_web_signup import FORM, raw_client, signup_on, supabase  # noqa: F401


def test_without_the_test_notice_sign_up_is_as_before(raw_client, signup_on, supabase, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "test_notice", False)
    page = raw_client.get("/signup").text
    assert "This is a test" not in page and 'name="accept"' not in page
    assert raw_client.post("/signup", data=FORM).status_code == 303


def test_sign_up_shows_the_notice_and_wants_it_accepted(raw_client, signup_on, supabase, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "test_notice", True)
    page = raw_client.get("/signup").text
    assert "This is a test version run by a person, not a company" in page
    assert "I won't look at it unless you ask me to help with a problem" in page
    assert "Nothing here is financial advice" in page and 'name="accept"' in page
    refused = raw_client.post("/signup", data=FORM)
    assert refused.status_code == 400 and "tick the box" in refused.text
    assert supabase["create_user"] == [], "no account without accepting"
    accepted = raw_client.post("/signup", data={**FORM, "accept": "1"})
    assert accepted.status_code == 303 and supabase["create_user"] == [FORM["email"]]


def test_the_profile_has_the_notice_and_a_feedback_link(client, monkeypatch):
    monkeypatch.setattr(settings, "test_notice", True)
    monkeypatch.setattr(settings, "feedback_email", "owner@example.com")
    page = client.get("/profile").text
    assert "About this test" in page and "Nothing here is financial advice" in page
    assert 'id="feedback"' in page
    link = page.split('id="feedback" href="')[1].split('"')[0].replace("&amp;", "&")
    parsed = urlparse(link)
    assert parsed.scheme == "mailto" and parsed.path == "owner@example.com"
    query = parse_qs(parsed.query)
    assert query["subject"] == ["finode feedback"]
    assert f"finode {VERSION}" in query["body"][0]
    assert "test@example.com" not in link, "no personal data in the link"


def test_without_settings_the_profile_is_as_before(client, monkeypatch):
    monkeypatch.setattr(settings, "test_notice", False)
    monkeypatch.setattr(settings, "feedback_email", None)
    page = client.get("/profile").text
    assert "About this test" not in page and "Send feedback" not in page


def test_the_first_run_card_names_the_currency_and_the_backup(client):
    page = client.get("/").text
    assert "Get started" in page and "Amounts are in <strong>INR</strong>" in page
    assert 'href="/settings#currency"' in page and 'href="/profile/data#backup"' in page
