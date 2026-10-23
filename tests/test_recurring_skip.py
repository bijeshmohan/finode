"""Skipping one occurrence of a recurring transaction without pausing it."""

from datetime import date, timedelta

from app.recurring_runner import run_once

from .test_recurring import accounts, rule, transactions  # noqa: F401  (fixtures and helpers)

NEXT_MONTH_START = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)


def future_rule(client, accounts, **fields):  # noqa: F811
    """Monthly, first occurrence a month ahead, so nothing is recorded yet."""
    return rule(client, accounts, start_date=str(NEXT_MONTH_START), **fields)


def skip(client, rid):
    return client.post(f"/api/recurring/{rid}/skip")


def test_skipping_moves_on_to_the_following_occurrence(client, accounts, session):  # noqa: F811
    created = future_rule(client, accounts)
    response = skip(client, created["rid"])
    assert response.status_code == 200
    read = response.json()
    after = (NEXT_MONTH_START.replace(day=1) + timedelta(days=32)).replace(day=1)
    assert read["skipped_date"] == str(NEXT_MONTH_START) and read["next_date"] == str(after)
    assert read["active"] is True and read["last_date"] is None
    assert transactions(session) == [], "nothing is recorded for a skipped occurrence"


def test_skipping_twice_skips_two(client, accounts):  # noqa: F811
    created = future_rule(client, accounts)
    first = skip(client, created["rid"]).json()
    second = skip(client, created["rid"]).json()
    assert second["skipped_date"] == first["next_date"] and second["next_date"] > first["next_date"]


def test_the_skipped_one_stays_skipped_when_the_rule_is_edited(client, accounts):  # noqa: F811
    created = future_rule(client, accounts)
    skipped = skip(client, created["rid"]).json()
    body = {
        "from_account": accounts["bank"], "to_account": accounts["rent"], "amount": "1600",
        "frequency": "monthly", "start_date": str(NEXT_MONTH_START), "payee": "Landlord",
    }
    edited = client.put(f"/api/recurring/{created['rid']}", json=body)
    assert edited.status_code == 200
    assert edited.json()["next_date"] == skipped["next_date"], "not the skipped date again"


def test_a_skipped_occurrence_is_never_recorded_later(client, accounts, session, monkeypatch):  # noqa: F811
    from contextlib import nullcontext

    from app.mcp_server import context

    monkeypatch.setattr(context, "session_factory", lambda: nullcontext(session))
    created = rule(client, accounts, start_date=str(date.today() + timedelta(days=1)), frequency="daily")
    skip(client, created["rid"])
    after = date.today() + timedelta(days=2)
    assert run_once(after) >= 1
    days = {r.date for r in transactions(session)}
    assert date.today() + timedelta(days=1) not in days and after in days


def test_a_rule_that_has_failed_can_skip_the_occurrence_that_failed(client, accounts, session):  # noqa: F811
    created = rule(client, accounts, start_date=str(date.today()), frequency="daily")
    from app.models.recurring import RecurringTransaction

    row = session.get(RecurringTransaction, __import__("uuid").UUID(created["rid"]))
    row.last_error = "2026-10-01: something went wrong"
    session.add(row)
    session.commit()
    read = skip(client, created["rid"]).json()
    assert read["last_error"] is None


def test_skipping_the_last_occurrence_ends_the_rule(client, accounts):  # noqa: F811
    created = future_rule(client, accounts, end_date=str(NEXT_MONTH_START + timedelta(days=5)))
    read = skip(client, created["rid"]).json()
    assert read["active"] is False


def test_a_paused_rule_cannot_skip(client, accounts):  # noqa: F811
    created = future_rule(client, accounts)
    client.post(f"/recurring/{created['rid']}/pause")
    response = skip(client, created["rid"])
    assert response.status_code == 400 and "resume it first" in response.json()["detail"]


def test_an_unknown_rule(client):
    assert skip(client, "00000000-0000-4000-8000-0000000000aa").status_code == 404


# ---- the page ------------------------------------------------------------------------------------------------------


def test_the_edit_page_offers_to_skip_and_says_what_was_skipped(client, accounts):  # noqa: F811
    created = future_rule(client, accounts)
    page = client.get(f"/recurring/{created['rid']}/edit").text
    assert f'hx-post="/recurring/{created["rid"]}/skip"' in page and "Just this once?" in page
    response = client.post(f"/recurring/{created['rid']}/skip")
    assert response.headers["HX-Redirect"] == "/recurring" and "recurring-skipped" in response.headers["set-cookie"]
    page = client.get(f"/recurring/{created['rid']}/edit").text
    assert "skipped" in page and "last recorded" not in page


def test_the_page_refuses_a_paused_rule_in_place(client, accounts):  # noqa: F811
    created = future_rule(client, accounts)
    client.post(f"/recurring/{created['rid']}/pause")
    bad = client.post(f"/recurring/{created['rid']}/skip")
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#form-error"
    assert "Just this once?" not in client.get(f"/recurring/{created['rid']}/edit").text
