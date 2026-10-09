"""Recurring transactions: when things fall due, recording them exactly once, and the pages around them."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from app.dependencies import get_db_session
from app.models.recurring import RecurringTransaction
from app.models.transaction import Transaction
from app.recurring_runner import run_once
from app.services.schedule import describe, first_after, first_on_or_after, occurrence

from .conftest import TEST_USER_ID


# ---- the arithmetic of dates -----------------------------------------------------------------------


def test_daily_and_weekly_occurrences():
    start = date(2026, 1, 1)
    assert occurrence(start, "daily", 3, 2) == date(2026, 1, 7)
    assert occurrence(start, "weekly", 2, 1) == date(2026, 1, 15)


def test_monthly_keeps_the_day_and_clamps_in_short_months():
    start = date(2026, 1, 31)
    assert [occurrence(start, "monthly", 1, n) for n in range(4)] == [
        date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30),
    ]
    assert occurrence(date(2026, 11, 15), "monthly", 3, 1) == date(2027, 2, 15), "wraps over the year"


def test_yearly_handles_leap_days():
    start = date(2024, 2, 29)
    assert occurrence(start, "yearly", 1, 1) == date(2025, 2, 28)
    assert occurrence(start, "yearly", 1, 4) == date(2028, 2, 29)


def test_finding_the_next_occurrence():
    start = date(2026, 1, 31)
    assert first_on_or_after(start, "monthly", 1, date(2025, 6, 1)) == start, "before the start: the start"
    assert first_on_or_after(start, "monthly", 1, date(2026, 2, 28)) == date(2026, 2, 28)
    assert first_after(start, "monthly", 1, date(2026, 2, 28)) == date(2026, 3, 31)
    assert first_on_or_after(date(2020, 1, 1), "daily", 1, date(2026, 5, 5)) == date(2026, 5, 5)
    assert first_on_or_after(date(2020, 1, 1), "weekly", 2, date(2026, 5, 5)) >= date(2026, 5, 5)


def test_describing_a_schedule():
    assert describe("monthly", 1) == "Every month" and describe("weekly", 2) == "Every 2 weeks"


# ---- recording what is due ---------------------------------------------------------------------------


@pytest.fixture
def accounts(client, root_accounts):
    def make(name, root, **extra):
        return client.post("/api/accounts/", json={"name": name, "parent_id": root_accounts[root], **extra}).json()["aid"]

    return {"bank": make("Bank", "Assets", balance="10000"), "rent": make("Rent", "Expenses")}


def rule(client, accounts, **fields):
    body = {
        "from_account": accounts["bank"], "to_account": accounts["rent"], "amount": "1500",
        "frequency": "monthly", "start_date": "2026-01-01", "payee": "Landlord", **fields,
    }
    response = client.post("/api/recurring/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def transactions(session):
    """What rules recorded (not the accounts' opening balances)."""
    return session.exec(
        Transaction.__table__.select().where(Transaction.created_via == "recurring").order_by(Transaction.date)
    ).all()


def test_a_rule_starting_in_the_past_records_every_missed_date(client, accounts, session):
    created = rule(client, accounts, start_date=str(date.today().replace(day=1)), frequency="daily")
    rows = transactions(session)
    assert len(rows) == date.today().day, "from the first of this month to today"
    assert {r.created_via for r in rows} == {"recurring"}
    assert created["rid"] and client.get(f"/api/recurring/{created['rid']}").json()["next_date"] > str(date.today())


def test_a_rule_starting_later_records_nothing_yet(client, accounts, session):
    created = rule(client, accounts, start_date="2999-01-01")
    assert transactions(session) == [] and created["next_date"] == "2999-01-01"


def test_recording_moves_the_money_and_is_idempotent(client, accounts, session):
    rule(client, accounts, start_date="2026-01-31")
    client.get("/api/recurring/")
    client.get("/api/recurring/")
    rows = transactions(session)
    assert [r.date for r in rows][:3] == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]
    assert len({r.date for r in rows}) == len(rows), "each date once, however often it runs"
    assert client.get(f"/api/accounts/{accounts['rent']}").json()["balance"] == str(Decimal("1500") * len(rows)) + ".00"


def test_each_occurrence_is_linked_and_marked(client, accounts, session):
    created = rule(client, accounts, start_date="2026-01-01")
    row = transactions(session)[0]
    assert str(row.recurring_id) == created["rid"] and row.recurring_date == date(2026, 1, 1)
    page = client.get("/transactions").text
    assert "Recurring" in page and "Landlord" in page
    api = next(t for t in client.get("/api/transactions/").json() if t["created_via"] == "recurring")
    assert api["recurring_id"] == created["rid"]


def test_the_end_date_stops_it(client, accounts, session):
    created = rule(client, accounts, start_date="2026-01-15", end_date="2026-03-20")
    assert [r.date for r in transactions(session)] == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]
    ended = client.get(f"/api/recurring/{created['rid']}").json()
    assert ended["active"] is False


def test_pausing_stops_it_and_resuming_skips_what_was_missed(client, accounts, session):
    created = rule(client, accounts, start_date="2999-01-01", frequency="daily")
    rid = created["rid"]
    assert client.post(f"/api/recurring/{rid}/pause").json()["active"] is False
    # pretend it was due a month ago while paused
    session.exec(RecurringTransaction.__table__.update().values(next_date=date(2026, 1, 1)))
    session.commit()
    client.get("/api/recurring/")
    assert transactions(session) == [], "paused: nothing recorded"
    resumed = client.post(f"/api/recurring/{rid}/resume").json()
    assert resumed["active"] is True and resumed["next_date"] >= str(date.today())
    assert all(r.date >= date.today() for r in transactions(session)), "nothing recorded for the paused days"


def test_resuming_an_ended_rule_explains(client, accounts):
    created = rule(client, accounts, start_date="2026-01-15", end_date="2026-02-20")
    response = client.post(f"/api/recurring/{created['rid']}/resume")
    assert response.status_code == 400 and "ended" in response.json()["detail"]


def test_editing_carries_on_after_what_was_recorded(client, accounts, session):
    created = rule(client, accounts, start_date="2026-01-01")
    before = len(transactions(session))
    body = {k: created[k] for k in ("from_account", "to_account", "frequency", "every", "start_date")}
    body.update(amount="2000", payee="New landlord")
    updated = client.put(f"/api/recurring/{created['rid']}", json=body)
    assert updated.status_code == 200 and updated.json()["amount"] == "2000.00"
    assert len(transactions(session)) == before, "what was recorded is not repeated"
    client.get("/api/recurring/")
    assert len(transactions(session)) == before


def test_deleting_keeps_what_was_recorded(client, accounts, session):
    created = rule(client, accounts, start_date="2026-01-01")
    count = len(transactions(session))
    assert client.delete(f"/api/recurring/{created['rid']}").status_code == 204
    assert len(transactions(session)) == count
    assert all(r.recurring_id is None for r in transactions(session))
    assert client.delete(f"/api/recurring/{created['rid']}").status_code == 404
    assert client.get("/api/recurring/").json() == []


def test_an_account_a_rule_uses_cannot_be_deleted(client, accounts):
    rule(client, accounts, start_date="2999-01-01")
    response = client.delete(f"/api/accounts/{accounts['rent']}")
    assert response.status_code == 409 or response.status_code == 400
    assert "recurring" in response.text


def test_a_rule_that_cannot_be_recorded_is_refused_or_reported(client, accounts, root_accounts, session):
    bad = client.post("/api/recurring/", json={
        "from_account": accounts["bank"], "to_account": accounts["bank"], "amount": "5",
        "frequency": "monthly", "start_date": "2026-01-01",
    })
    assert bad.status_code == 400 and "differ" in bad.json()["detail"]
    wallet = client.post("/api/accounts/", json={"name": "Wallet", "parent_id": root_accounts["Assets"]}).json()["aid"]
    created = rule(client, {"bank": wallet, "rent": accounts["rent"]}, start_date="2999-01-01")
    # the source later gains a sub-account, so it can no longer be posted to
    assert client.post("/api/accounts/", json={"name": "Sub", "parent_id": wallet}).status_code == 201
    session.exec(RecurringTransaction.__table__.update().values(start_date=date(2026, 1, 1), next_date=date(2026, 1, 1)))
    session.commit()
    client.get("/api/recurring/")
    read = client.get(f"/api/recurring/{created['rid']}").json()
    assert read["last_error"] and read["active"] is True and transactions(session) == []


def test_validation_and_limits(client, accounts, monkeypatch):
    for body in ({"every": 0}, {"amount": "-1"}, {"frequency": "hourly"}, {"end_date": "2025-01-01"}):
        response = client.post("/api/recurring/", json={
            "from_account": accounts["bank"], "to_account": accounts["rent"], "amount": "1",
            "start_date": "2026-01-01", **body,
        })
        assert response.status_code == 422, body
    monkeypatch.setattr("app.services.recurring.MAX_RULES", 1)
    rule(client, accounts, start_date="2999-01-01")
    again = client.post("/api/recurring/", json={
        "from_account": accounts["bank"], "to_account": accounts["rent"], "amount": "1", "start_date": "2999-01-01",
    })
    assert again.status_code == 400 and "at most" in again.json()["detail"]


def test_another_users_rule_is_invisible(client, accounts, session):
    created = rule(client, accounts, start_date="2999-01-01")
    session.exec(RecurringTransaction.__table__.update().values(user=UUID("00000000-0000-4000-8000-000000000002")))
    session.commit()
    assert client.get(f"/api/recurring/{created['rid']}").status_code == 404
    assert client.get("/api/recurring/").json() == []


def test_a_conversion_rule_needs_the_received_amount(client, accounts, root_accounts):
    usd = client.post("/api/accounts/", json={"name": "Dollars", "parent_id": root_accounts["Assets"], "commodity": "USD"}).json()["aid"]
    missing = client.post("/api/recurring/", json={
        "from_account": accounts["bank"], "to_account": usd, "amount": "8350", "start_date": "2999-01-01",
    })
    assert missing.status_code == 400 and "how much USD arrives" in missing.json()["detail"]
    ok = client.post("/api/recurring/", json={
        "from_account": accounts["bank"], "to_account": usd, "amount": "8350", "received_amount": "100", "start_date": "2999-01-01",
    })
    assert ok.status_code == 201


# ---- the background run ------------------------------------------------------------------------------


def test_the_background_run_records_for_every_user(client, accounts, session, monkeypatch):
    from contextlib import nullcontext

    from app.mcp_server import context

    monkeypatch.setattr(context, "session_factory", lambda: nullcontext(session))
    rule(client, accounts, start_date="2999-01-01", frequency="daily")
    session.exec(RecurringTransaction.__table__.update().values(start_date=date(2026, 1, 1), next_date=date(2026, 1, 1)))
    session.commit()
    recorded = run_once(date(2026, 1, 3))
    assert recorded == 3 and [r.date for r in transactions(session)] == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    assert run_once(date(2026, 1, 3)) == 0, "nothing left to do"


def test_a_failing_user_does_not_stop_the_run(client, accounts, session, monkeypatch):
    from contextlib import nullcontext

    from app.mcp_server import context
    from app.services.recurring import RecurringService

    monkeypatch.setattr(context, "session_factory", lambda: nullcontext(session))
    rule(client, accounts, start_date="2999-01-01")
    session.exec(RecurringTransaction.__table__.update().values(next_date=date(2026, 1, 1)))
    session.commit()

    def boom(self, today=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(RecurringService, "process_due", boom)
    assert run_once(date(2026, 2, 1)) == 0


# ---- the pages -----------------------------------------------------------------------------------


def test_the_list_page_shows_rules_and_an_empty_state(client, accounts):
    assert "No recurring transactions yet." in client.get("/recurring").text
    rule(client, accounts, start_date="2999-01-01")
    page = client.get("/recurring").text
    assert "Landlord" in page and "Every month" in page and "Assets › Bank → Expenses › Rent" in page
    assert 'href="/recurring/new"' in page


def test_settings_and_transactions_pages_link_to_it(client):
    assert 'href="/recurring"' in client.get("/settings").text
    assert 'href="/recurring"' in client.get("/transactions").text


def test_creating_through_the_form(client, accounts, session):
    page = client.get("/recurring/new")
    assert page.status_code == 200 and 'name="frequency"' in page.text and 'name="start"' in page.text
    response = client.post("/recurring", data={
        "amount": "1500", "from_account": accounts["bank"], "to_account": accounts["rent"],
        "frequency": "monthly", "every": "1", "start": "2999-01-01", "payee": "Landlord",
    })
    assert response.headers["HX-Redirect"] == "/recurring" and "recurring-saved" in response.headers["set-cookie"]
    assert "Landlord" in client.get("/recurring").text


def test_the_form_reports_mistakes(client, accounts):
    def post(**data):
        base = {"amount": "5", "from_account": accounts["bank"], "to_account": accounts["rent"],
                "frequency": "monthly", "every": "1", "start": "2999-01-01"}
        response = client.post("/recurring", data={**base, **data})
        assert response.status_code == 400 and response.headers["HX-Retarget"] == "#form-error"
        return response.text

    assert "choose both" in post(from_account="")
    assert "whole number" in post(every="x")
    assert "start date" in post(start="")
    assert "not a valid date" in post(end="31/12")
    assert "end date cannot be before" in post(end="2998-01-01")
    assert "differ" in post(to_account=accounts["bank"])


def test_editing_pausing_and_deleting_through_the_pages(client, accounts):
    created = rule(client, accounts, start_date="2999-01-01")
    rid = created["rid"]
    edit = client.get(f"/recurring/{rid}/edit")
    assert edit.status_code == 200 and "Landlord" in edit.text and "Pause" in edit.text
    saved = client.post(f"/recurring/{rid}/edit", data={
        "amount": "1600", "from_account": accounts["bank"], "to_account": accounts["rent"],
        "frequency": "weekly", "every": "2", "start": "2999-01-01", "payee": "Landlord",
    })
    assert saved.headers["HX-Redirect"] == "/recurring"
    assert "Every 2 weeks" in client.get("/recurring").text
    client.post(f"/recurring/{rid}/pause")
    page = client.get("/recurring").text
    assert "paused" in page and "Paused or ended" in page
    assert "Resume" in client.get(f"/recurring/{rid}/edit").text
    client.post(f"/recurring/{rid}/resume")
    assert client.post(f"/recurring/{rid}/delete").headers["HX-Redirect"] == "/recurring"
    assert client.get(f"/recurring/{rid}/edit").status_code == 404
    missing = "00000000-0000-4000-8000-0000000000aa"
    for action in ("pause", "resume", "delete"):
        assert client.post(f"/recurring/{missing}/{action}", data={}).status_code == 404
    full = {"amount": "1", "from_account": accounts["bank"], "to_account": accounts["rent"], "start": "2999-01-01"}
    assert client.post(f"/recurring/{missing}/edit", data=full).status_code == 404


def test_opening_the_dashboard_catches_up(client, accounts, session):
    rule(client, accounts, start_date="2999-01-01", frequency="daily")
    session.exec(RecurringTransaction.__table__.update().values(next_date=date.today()))
    session.commit()
    assert client.get("/").status_code == 200
    assert len(transactions(session)) == 1
