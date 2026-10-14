"""FINODE_TIMEZONE decides what "today" is."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app import clock
from app.config import Settings, settings


@pytest.fixture
def kolkata_after_midnight(monkeypatch: pytest.MonkeyPatch):
    """16 October 00:30 in India, which is still 15 October 19:00 in UTC."""
    monkeypatch.setattr(settings, "timezone", "Asia/Kolkata")
    monkeypatch.setattr(clock, "local_now", lambda: datetime(2031, 10, 16, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata")))


def test_the_zone_decides_the_day(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "timezone", "Pacific/Kiritimati")  # UTC+14
    ahead = clock.local_now()
    monkeypatch.setattr(settings, "timezone", "Etc/GMT+12")  # UTC-12
    behind = clock.local_now()
    assert ahead.utcoffset().total_seconds() == 14 * 3600 and behind.utcoffset().total_seconds() == -12 * 3600
    assert abs((ahead - behind).total_seconds()) < 5  # the same moment, two clocks
    assert (ahead.date() - behind.date()).days in (1, 2)


def test_without_a_zone_the_servers_clock_is_used(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "timezone", None)
    assert clock.local_today() == datetime.now().astimezone().date()


def test_midnight_is_given_as_a_utc_moment(kolkata_after_midnight):
    midnight = clock.local_midnight_utc()
    assert midnight == datetime(2031, 10, 15, 18, 30, tzinfo=timezone.utc)


def test_the_setting_must_name_a_real_zone():
    assert Settings(_env_file=None, timezone="Asia/Kolkata").timezone == "Asia/Kolkata"
    assert Settings(_env_file=None, timezone="").timezone is None
    with pytest.raises(ValueError, match="time zone name"):
        Settings(_env_file=None, timezone="Mars/Olympus")


def test_new_entries_and_the_pages_use_that_day(client, account, expense_account, kolkata_after_midnight):
    made = client.post(
        "/api/transactions/",
        json={"postings": [
            {"account": expense_account["aid"], "side": "debit", "amount": "5"},
            {"account": account["aid"], "side": "credit", "amount": "5"},
        ]},
    )
    assert made.status_code == 201 and made.json()["date"] == "2031-10-16"
    assert "2031-10-16" in client.get("/transactions/new").text
    assert "Today" in client.get("/transactions").text
    assert client.get("/api/budget/").json()["month"] == "2031-10-01"
