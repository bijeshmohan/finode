"""Skipping one occurrence of a recurring transaction without pausing it."""

from datetime import date, timedelta

from finode.recurring_runner import run_once
from tests.budget.test_recurring import accounts, rule, transactions  # noqa: F401  (fixtures and helpers)

NEXT_MONTH_START = (date.today().replace(day=1) + timedelta(days=32)).replace(day=1)


def future_rule(client, accounts, **fields):
    """Monthly, first occurrence a month ahead, so nothing is recorded yet."""
    return rule(client, accounts, start_date=str(NEXT_MONTH_START), **fields)


def skip(client, recurring_id):
    return client.post(f"/api/recurring/{recurring_id}/skip")


def test_skipping_moves_on_to_the_following_occurrence(client, accounts, session):
    created = future_rule(client, accounts)
    response = skip(client, created["id"])
    assert response.status_code == 200
    read = response.json()
    after = (NEXT_MONTH_START.replace(day=1) + timedelta(days=32)).replace(day=1)
    assert read["skipped_date"] == str(NEXT_MONTH_START) and read["next_date"] == str(after)
    assert read["active"] is True and read["last_date"] is None
    assert transactions(session) == [], "nothing is recorded for a skipped occurrence"


def test_skipping_twice_skips_two(client, accounts):
    created = future_rule(client, accounts)
    first = skip(client, created["id"]).json()
    second = skip(client, created["id"]).json()
    assert second["skipped_date"] == first["next_date"] and second["next_date"] > first["next_date"]


def test_the_skipped_one_stays_skipped_when_the_rule_is_edited(client, accounts):
    created = future_rule(client, accounts)
    skipped = skip(client, created["id"]).json()
    body = {
        "from_account_id": accounts["bank"],
        "to_account_id": accounts["expenses"],
        "category_id": accounts["rent"],
        "amount": "1600",
        "frequency": "monthly",
        "start_date": str(NEXT_MONTH_START),
        "payee": "Landlord",
    }
    edited = client.put(f"/api/recurring/{created['id']}", json=body)
    assert edited.status_code == 200
    assert edited.json()["next_date"] == skipped["next_date"], "not the skipped date again"


def test_a_skipped_occurrence_is_never_recorded_later(client, accounts, session, monkeypatch):
    from contextlib import nullcontext

    from finode.mcp_server import context

    monkeypatch.setattr(context, "session_factory", lambda: nullcontext(session))
    created = rule(client, accounts, start_date=str(date.today() + timedelta(days=1)), frequency="daily")
    skip(client, created["id"])
    after = date.today() + timedelta(days=2)
    assert run_once(after) >= 1
    days = {r.date for r in transactions(session)}
    assert date.today() + timedelta(days=1) not in days and after in days


def test_a_rule_that_has_failed_can_skip_the_occurrence_that_failed(client, accounts, session):
    created = rule(client, accounts, start_date=str(date.today()), frequency="daily")
    from finode.models.recurring import RecurringTransaction

    row = session.get(RecurringTransaction, __import__("uuid").UUID(created["id"]))
    row.last_error = "2026-10-01: something went wrong"
    session.add(row)
    session.commit()
    read = skip(client, created["id"]).json()
    assert read["last_error"] is None


def test_skipping_the_last_occurrence_ends_the_rule(client, accounts):
    created = future_rule(client, accounts, end_date=str(NEXT_MONTH_START + timedelta(days=5)))
    read = skip(client, created["id"]).json()
    assert read["active"] is False


def test_a_paused_rule_cannot_skip(client, accounts):
    created = future_rule(client, accounts)
    client.post(f"/api/recurring/{created['id']}/pause")
    response = skip(client, created["id"])
    assert response.status_code == 400 and "resume it first" in response.json()["detail"]


def test_an_unknown_rule(client):
    assert skip(client, "00000000-0000-4000-8000-0000000000aa").status_code == 404


# ---- the page ------------------------------------------------------------------------------------------------------


def test_skipping_moves_the_next_date_and_the_list_says_it_is_active(client, accounts):
    created = future_rule(client, accounts)
    assert skip(client, created["id"]).status_code == 200
    moved = client.get(f"/api/recurring/{created['id']}").json()
    assert moved["next_date"] > created["next_date"], "the next one is skipped"
    assert [r["status"] for r in client.get("/api/views/recurring").json()["live"]] == ["active"]
