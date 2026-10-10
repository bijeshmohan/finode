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


def form(accounts, amount="1500", **extra):
    """What the page posts: a row on each side, like the transaction form."""
    return {
        "account": [accounts["rent"], accounts["bank"]], "side": ["debit", "credit"], "amount": [amount, amount],
        "frequency": "monthly", "every": "1", "start": "2999-01-01", **extra,
    }


def test_creating_through_the_form(client, accounts, session):
    page = client.get("/recurring/new")
    assert page.status_code == 200 and 'name="frequency"' in page.text and 'name="start"' in page.text
    assert 'name="total"' in page.text and 'data-rows="credit"' in page.text and 'data-rows="debit"' in page.text
    response = client.post("/recurring", data=form(accounts, payee="Landlord"))
    assert client.get("/api/recurring/").json()[0]["from_account"] == accounts["bank"], "one on each side stays a plain rule"
    assert response.headers["HX-Redirect"] == "/recurring" and "recurring-saved" in response.headers["set-cookie"]
    assert "Landlord" in client.get("/recurring").text


def test_the_form_reports_mistakes(client, accounts):
    def post(**data):
        response = client.post("/recurring", data={**form(accounts, "5"), **data})
        assert response.status_code == 400 and response.headers["HX-Retarget"] == "#form-error"
        return response.text

    assert "where the money comes from" in post(account=[accounts["rent"], ""], amount=["5", ""])
    assert "whole number" in post(every="x")
    assert "start date" in post(start="")
    assert "not a valid date" in post(end="31/12")
    assert "end date cannot be before" in post(end="2998-01-01")
    assert "balance" in post(amount=["5", "6"]).lower()


def test_editing_pausing_and_deleting_through_the_pages(client, accounts):
    created = rule(client, accounts, start_date="2999-01-01")
    rid = created["rid"]
    edit = client.get(f"/recurring/{rid}/edit")
    assert edit.status_code == 200 and "Landlord" in edit.text and "Pause" in edit.text
    saved = client.post(f"/recurring/{rid}/edit", data=form(accounts, "1600", frequency="weekly", every="2", payee="Landlord"))
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
    assert client.post(f"/recurring/{missing}/edit", data=form(accounts, "1")).status_code == 404


def test_opening_the_dashboard_catches_up(client, accounts, session):
    rule(client, accounts, start_date="2999-01-01", frequency="daily")
    session.exec(RecurringTransaction.__table__.update().values(next_date=date.today()))
    session.commit()
    assert client.get("/").status_code == 200
    assert len(transactions(session)) == 1


# ---- split rules -------------------------------------------------------------------------------------------


@pytest.fixture
def split_accounts(client, accounts, root_accounts):
    extra = {
        name: client.post("/api/accounts/", json={"name": name, "parent_id": root_accounts[root]}).json()["aid"]
        for name, root in (("Water", "Expenses"), ("Savings", "Assets"))
    }
    return {**accounts, **extra}


def split_rule(client, a, **fields):
    body = {
        "postings": [
            {"account": a["rent"], "side": "debit", "amount": "1000"},
            {"account": a["Water"], "side": "debit", "amount": "200"},
            {"account": a["bank"], "side": "credit", "amount": "1200"},
        ],
        "frequency": "monthly", "start_date": "2026-01-01", "payee": "Landlord", **fields,
    }
    response = client.post("/api/recurring/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_split_rule_records_every_row(client, split_accounts, session):
    created = split_rule(client, split_accounts)
    assert created["from_account"] is None and len(created["postings"]) == 3
    recorded = transactions(session)
    assert len(recorded) > 1
    first = client.get("/api/transactions/", params={"date_from": "2026-01-01", "date_to": "2026-01-01"}).json()
    split = next(t for t in first if t["payee"] == "Landlord")
    assert sorted((p["side"], p["amount"]) for p in split["postings"]) == [
        ("credit", "1200.00"), ("debit", "1000.00"), ("debit", "200.00"),
    ]
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    assert client.get(f"/api/recurring/{created['rid']}").json()["postings"][2]["side"] == "credit"


def test_a_split_rule_must_balance_and_not_mix_shapes(client, split_accounts):
    a = split_accounts
    unbalanced = {"postings": [
        {"account": a["rent"], "side": "debit", "amount": "1000"},
        {"account": a["bank"], "side": "credit", "amount": "900"},
    ], "start_date": "2999-01-01"}
    assert client.post("/api/recurring/", json=unbalanced).status_code == 400
    mixed = {**unbalanced, "from_account": a["bank"], "amount": "5"}
    assert client.post("/api/recurring/", json=mixed).status_code == 422
    assert client.post("/api/recurring/", json={"start_date": "2999-01-01"}).status_code == 422
    one = {"postings": unbalanced["postings"][:1], "start_date": "2999-01-01"}
    assert client.post("/api/recurring/", json=one).status_code == 422


def test_a_split_rule_can_be_edited_into_a_plain_one_and_back(client, split_accounts):
    a = split_accounts
    rid = split_rule(client, a, start_date="2999-01-01")["rid"]
    plain = {"from_account": a["bank"], "to_account": a["rent"], "amount": "1500", "start_date": "2999-01-01"}
    updated = client.put(f"/api/recurring/{rid}", json=plain).json()
    assert updated["postings"] == [] and updated["amount"] == "1500.00"
    again = client.put(f"/api/recurring/{rid}", json={
        "postings": [
            {"account": a["rent"], "side": "debit", "amount": "1"},
            {"account": a["Water"], "side": "debit", "amount": "2"},
            {"account": a["bank"], "side": "credit", "amount": "3"},
        ], "start_date": "2999-01-01"}).json()
    assert len(again["postings"]) == 3 and again["from_account"] is None


def test_an_account_a_split_rule_uses_cannot_be_deleted(client, split_accounts):
    split_rule(client, split_accounts, start_date="2999-01-01")
    assert client.delete(f"/api/accounts/{split_accounts['Water']}").status_code == 409


def test_deleting_a_split_rule_removes_its_rows(client, split_accounts, session):
    from app.models.recurring import RecurringPosting

    rid = split_rule(client, split_accounts, start_date="2999-01-01")["rid"]
    assert len(session.exec(RecurringPosting.__table__.select()).all()) == 3
    assert client.delete(f"/api/recurring/{rid}").status_code in (200, 204)
    assert session.exec(RecurringPosting.__table__.select()).all() == []


def test_the_form_saves_a_split_and_shows_it_again(client, split_accounts):
    a = split_accounts
    response = client.post("/recurring", data={
        "account": [a["rent"], a["Water"], a["bank"]], "side": ["debit", "debit", "credit"],
        "amount": ["1000", "200", "1200"], "frequency": "monthly", "every": "1", "start": "2999-01-01", "payee": "Landlord",
    })
    assert response.headers["HX-Redirect"] == "/recurring", response.text
    [stored] = client.get("/api/recurring/").json()
    assert stored["from_account"] is None and len(stored["postings"]) == 3
    listing = client.get("/recurring").text
    assert "Landlord" in listing and "Bank" in listing and "Rent, Water" in listing and "1,200.00" in listing
    page = client.get(f"/recurring/{stored['rid']}/edit").text
    debit = page[page.index('data-rows="debit"'):]
    assert page.count('class="txn-row"') >= 3 and 'value="1200.00"' in page and "data-touched" in debit
    assert 'value="1000.00"' in page and 'value="200.00"' in page


def test_the_edit_page_shows_a_plain_rule_as_one_row_each_side(client, accounts):
    created = rule(client, accounts, start_date="2999-01-01")
    page = client.get(f"/recurring/{created['rid']}/edit").text
    credit = page[page.index('data-rows="credit"'):page.index('data-rows="debit"')]
    assert credit.count('class="txn-row"') == 1 and 'value="1500.00"' in page


def test_assistants_see_split_rules(session, client, split_accounts):
    import asyncio

    from .mcputil import make_token, mcp_client, payload, running_app

    split_rule(client, split_accounts, start_date="2999-01-01")

    async def go():
        async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
            return payload(await c.call_tool("list_recurring", {}))["recurring"]

    [item] = asyncio.run(go())
    assert "from" not in item and len(item["postings"]) == 3
    assert {p["side"] for p in item["postings"]} == {"debit", "credit"} and item["postings"][0]["account"]


def test_the_recurring_form_has_the_kind_buttons(client, accounts):
    new = client.get("/recurring/new").text
    assert 'name="kind" value="expense"' in new and ">Transfer</button>" in new
    created = rule(client, accounts, start_date="2999-01-01")
    assert 'name="kind" value="expense"' in client.get(f"/recurring/{created['rid']}/edit").text
