"""Recurring transactions: when things fall due, recording them exactly once, and the pages around them."""

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from finode.models.recurring import RecurringTransaction
from finode.models.transaction import Transaction
from finode.recurring_runner import run_once
from finode.services.schedule import describe, first_after, first_on_or_after, occurrence
from tests.books import post_account
from tests.conftest import TEST_USER_ID

# ---- the arithmetic of dates -----------------------------------------------------------------------


def test_daily_and_weekly_occurrences():
    start = date(2026, 1, 1)
    assert occurrence(start, "daily", 3, 2) == date(2026, 1, 7)
    assert occurrence(start, "weekly", 2, 1) == date(2026, 1, 15)


def test_monthly_keeps_the_day_and_clamps_in_short_months():
    start = date(2026, 1, 31)
    assert [occurrence(start, "monthly", 1, n) for n in range(4)] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
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
        return post_account(client, {"name": name, "parent_id": root_accounts[root], **extra}).json()["id"]

    return {
        "bank": make("Bank", "Assets", balance="10000"),
        "rent": make("Rent", "Expenses"),
        "expenses": root_accounts["Expenses"],
    }


def rule(client, accounts, **fields):
    body = {
        "from_account_id": accounts["bank"],
        "to_account_id": accounts["expenses"],
        "category_id": accounts["rent"],
        "amount": "1500",
        "frequency": "monthly",
        "start_date": "2026-01-01",
        "payee": "Landlord",
        **fields,
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
    assert created["id"] and client.get(f"/api/recurring/{created['id']}").json()["next_date"] > str(date.today())


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
    expenses = next(a["id"] for a in client.get("/api/accounts/").json() if a["name"] == "Expenses")
    assert client.get(f"/api/accounts/{expenses}").json()["balance"] == str(Decimal("1500") * len(rows)) + ".00"


def test_each_occurrence_is_linked_and_marked(client, accounts, session):
    created = rule(client, accounts, start_date="2026-01-01")
    row = transactions(session)[0]
    assert str(row.recurring_id) == created["id"] and row.recurring_date == date(2026, 1, 1)
    [listed] = [
        r for r in client.get("/api/views/transactions", params={"month": "2026-01"}).json()["rows"] if r["recurring"]
    ]
    assert listed["title"] == "Landlord", "the list marks it as recurring"
    api = next(t for t in client.get("/api/transactions/").json() if t["created_via"] == "recurring")
    assert api["recurring_id"] == created["id"]


def test_the_end_date_stops_it(client, accounts, session):
    created = rule(client, accounts, start_date="2026-01-15", end_date="2026-03-20")
    assert [r.date for r in transactions(session)] == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]
    ended = client.get(f"/api/recurring/{created['id']}").json()
    assert ended["active"] is False


def test_pausing_stops_it_and_resuming_skips_what_was_missed(client, accounts, session):
    created = rule(client, accounts, start_date="2999-01-01", frequency="daily")
    recurring_id = created["id"]
    assert client.post(f"/api/recurring/{recurring_id}/pause").status_code == 200
    assert client.get(f"/api/recurring/{recurring_id}").json()["active"] is False
    # pretend it was due a month ago while paused
    session.exec(RecurringTransaction.__table__.update().values(next_date=date(2026, 1, 1)))
    session.commit()
    client.get("/api/recurring/")
    assert transactions(session) == [], "paused: nothing recorded"
    assert client.post(f"/api/recurring/{recurring_id}/resume").status_code == 200
    resumed = client.get(f"/api/recurring/{recurring_id}").json()
    assert resumed["active"] is True and resumed["next_date"] >= str(date.today())
    assert all(r.date >= date.today() for r in transactions(session)), "nothing recorded for the paused days"


def test_resuming_an_ended_rule_explains(client, accounts):
    created = rule(client, accounts, start_date="2026-01-15", end_date="2026-02-20")
    response = client.post(f"/api/recurring/{created['id']}/resume")
    assert response.status_code == 400 and "ended" in response.json()["detail"]


def test_editing_carries_on_after_what_was_recorded(client, accounts, session):
    created = rule(client, accounts, start_date="2026-01-01")
    before = len(transactions(session))
    body = {k: created[k] for k in ("from_account_id", "to_account_id", "frequency", "every", "start_date")}
    body.update(amount="2000", payee="New landlord")
    updated = client.put(f"/api/recurring/{created['id']}", json=body)
    assert updated.status_code == 200 and updated.json()["amount"] == "2000.00"
    assert len(transactions(session)) == before, "what was recorded is not repeated"
    client.get("/api/recurring/")
    assert len(transactions(session)) == before


def test_deleting_keeps_what_was_recorded(client, accounts, session):
    created = rule(client, accounts, start_date="2026-01-01")
    count = len(transactions(session))
    assert client.delete(f"/api/recurring/{created['id']}").status_code == 204
    assert len(transactions(session)) == count
    assert all(r.recurring_id is None for r in transactions(session))
    assert client.delete(f"/api/recurring/{created['id']}").status_code == 404
    assert client.get("/api/recurring/").json() == []


def test_a_category_a_rule_uses_cannot_be_deleted(client, accounts):
    rule(client, accounts, start_date="2999-01-01")
    response = client.post(f"/api/categories/{accounts['rent']}/delete")
    assert response.status_code == 400
    assert "recurring" in response.text


def test_a_rule_that_cannot_be_recorded_is_refused_or_reported(client, accounts, root_accounts, session):
    bad = client.post(
        "/api/recurring/",
        json={
            "from_account_id": accounts["bank"],
            "to_account_id": accounts["bank"],
            "amount": "5",
            "frequency": "monthly",
            "start_date": "2026-01-01",
        },
    )
    assert bad.status_code == 400 and "differ" in bad.json()["detail"]
    wallet = post_account(client, {"name": "Wallet", "parent_id": root_accounts["Assets"]}).json()["id"]
    created = rule(client, {**accounts, "bank": wallet}, start_date="2999-01-01")
    # the source is later closed behind the rule's back (the app refuses it while a rule uses it)
    from finode.models.account import Account

    session.exec(Account.__table__.update().where(Account.id == UUID(wallet)).values(closed_on=date(2025, 12, 31)))
    session.exec(
        RecurringTransaction.__table__.update().values(start_date=date(2026, 1, 1), next_date=date(2026, 1, 1))
    )
    session.commit()
    client.get("/api/recurring/")
    read = client.get(f"/api/recurring/{created['id']}").json()
    assert read["last_error"] and read["active"] is True and transactions(session) == []


def test_validation_and_limits(client, accounts, monkeypatch):
    for body in ({"every": 0}, {"amount": "-1"}, {"frequency": "hourly"}, {"end_date": "2025-01-01"}):
        response = client.post(
            "/api/recurring/",
            json={
                "from_account_id": accounts["bank"],
                "to_account_id": accounts["rent"],
                "amount": "1",
                "start_date": "2026-01-01",
                **body,
            },
        )
        assert response.status_code == 422, body
    monkeypatch.setattr("finode.services.recurring.MAX_RULES", 1)
    rule(client, accounts, start_date="2999-01-01")
    again = client.post(
        "/api/recurring/",
        json={
            "from_account_id": accounts["bank"],
            "to_account_id": accounts["rent"],
            "amount": "1",
            "start_date": "2999-01-01",
        },
    )
    assert again.status_code == 400 and "at most" in again.json()["detail"]


def test_another_users_rule_is_invisible(client, accounts, session):
    created = rule(client, accounts, start_date="2999-01-01")
    session.exec(RecurringTransaction.__table__.update().values(user_id=UUID("00000000-0000-4000-8000-000000000002")))
    session.commit()
    assert client.get(f"/api/recurring/{created['id']}").status_code == 404
    assert client.get("/api/recurring/").json() == []


# ---- the background run ------------------------------------------------------------------------------


def test_the_background_run_records_for_every_user(client, accounts, session, monkeypatch):
    from contextlib import nullcontext

    from finode.mcp_server import context

    monkeypatch.setattr(context, "session_factory", lambda: nullcontext(session))
    rule(client, accounts, start_date="2999-01-01", frequency="daily")
    session.exec(
        RecurringTransaction.__table__.update().values(start_date=date(2026, 1, 1), next_date=date(2026, 1, 1))
    )
    session.commit()
    recorded = run_once(date(2026, 1, 3))
    assert recorded == 3 and [r.date for r in transactions(session)] == [
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    ]
    assert run_once(date(2026, 1, 3)) == 0, "nothing left to do"


def test_a_failing_user_does_not_stop_the_run(client, accounts, session, monkeypatch):
    from contextlib import nullcontext

    from finode.mcp_server import context
    from finode.services.recurring import RecurringService

    monkeypatch.setattr(context, "session_factory", lambda: nullcontext(session))
    rule(client, accounts, start_date="2999-01-01")
    session.exec(RecurringTransaction.__table__.update().values(next_date=date(2026, 1, 1)))
    session.commit()

    def boom(self, today=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(RecurringService, "process_due", boom)
    assert run_once(date(2026, 2, 1)) == 0


def test_trouble_recording_what_is_due_never_stops_a_page_and_is_logged(client, accounts, monkeypatch, caplog):
    """Home, Transactions and the Recurring views record what has fallen due as they open: a problem there is written to
    the log, not shown."""
    from finode.services.recurring import RecurringService

    def boom(self, today=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(RecurringService, "process_due", boom)
    with caplog.at_level("ERROR", logger="finode.recurring"):
        assert client.get("/api/views/home").status_code == 200
        assert client.get("/api/views/transactions").status_code == 200
        assert client.get("/api/views/recurring").status_code == 200
    assert len([r for r in caplog.records if r.exc_info and "boom" in str(r.exc_info[1])]) == 3


# ---- the views and the form ---------------------------------------------------------------------------


def test_the_list_shows_rules_and_is_empty_without_any(client, accounts):
    assert client.get("/api/views/recurring").json() == {"live": [], "stopped": []}
    rule(client, accounts, start_date="2999-01-01")
    [row] = client.get("/api/views/recurring").json()["live"]
    assert (row["title"], row["schedule"], row["status"]) == ("Landlord", "Every month", "active")


def test_the_form_reports_mistakes(client, accounts):
    from tests.api.test_api_recurring_form import form, plain, row

    def refused(body):
        answer = client.post("/api/recurring/form", json=body)
        assert answer.status_code in (400, 422), answer.text
        return answer.text

    assert "every" in refused(form(plain(accounts), every="x")).lower()
    assert "start" in refused(form(plain(accounts), start_date=None)).lower()
    assert "date" in refused(form(plain(accounts), end_date="31/12")).lower()
    assert "end date cannot be before" in refused(form(plain(accounts), end_date="2998-01-01"))
    unbalanced = [row(accounts["bank"], "credit", "5"), row(accounts["rent"], "debit", "6")]
    assert "balance" in refused(form(unbalanced)).lower()
    assert client.get("/api/recurring/").json() == [], "nothing is saved"


def test_editing_pausing_and_deleting(client, accounts):
    from tests.api.test_api_recurring_form import form, plain

    created = rule(client, accounts, start_date="2999-01-01")
    recurring_id = created["id"]
    saved = client.put(
        f"/api/recurring/{recurring_id}/form", json=form(plain(accounts, "1600"), frequency="weekly", every=2)
    )
    assert saved.status_code == 200, saved.text
    assert client.get("/api/views/recurring").json()["live"][0]["schedule"] == "Every 2 weeks"
    client.post(f"/api/recurring/{recurring_id}/pause")
    [paused] = client.get("/api/views/recurring").json()["stopped"]
    assert paused["status"] == "paused"
    client.post(f"/api/recurring/{recurring_id}/resume")
    assert client.delete(f"/api/recurring/{recurring_id}").status_code == 204
    assert client.get("/api/views/recurring-form", params={"recurring_id": recurring_id}).status_code == 404
    missing = "00000000-0000-4000-8000-0000000000aa"
    for action in ("pause", "resume", "skip"):
        assert client.post(f"/api/recurring/{missing}/{action}").status_code == 404, action
    assert client.put(f"/api/recurring/{missing}/form", json=form(plain(accounts, "1"))).status_code == 404


def test_opening_home_catches_up(client, accounts, session):
    rule(client, accounts, start_date="2999-01-01", frequency="daily")
    session.exec(RecurringTransaction.__table__.update().values(next_date=date.today()))
    session.commit()
    assert client.get("/api/views/home").status_code == 200
    assert len(transactions(session)) == 1


# ---- split rules -------------------------------------------------------------------------------------------


@pytest.fixture
def split_accounts(client, accounts, root_accounts):
    extra = {
        name: post_account(client, {"name": name, "parent_id": root_accounts[root]}).json()["id"]
        for name, root in (("Water", "Expenses"), ("Savings", "Assets"))
    }
    return {**accounts, **extra}


def split_rule(client, a, **fields):
    body = {
        "postings": [
            {"category_id": a["rent"], "side": "debit", "amount": "1000"},
            {"category_id": a["Water"], "side": "debit", "amount": "200"},
            {"account_id": a["bank"], "side": "credit", "amount": "1200"},
        ],
        "frequency": "monthly",
        "start_date": "2026-01-01",
        "payee": "Landlord",
        **fields,
    }
    response = client.post("/api/recurring/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_a_split_rule_records_every_row(client, split_accounts, session):
    created = split_rule(client, split_accounts)
    assert created["from_account_id"] is None and len(created["postings"]) == 3
    recorded = transactions(session)
    assert len(recorded) > 1
    first = client.get("/api/transactions/", params={"date_from": "2026-01-01", "date_to": "2026-01-01"}).json()
    split = next(t for t in first if t["payee"] == "Landlord")
    assert sorted((p["side"], p["amount"]) for p in split["postings"]) == [
        ("credit", "1200.00"),
        ("debit", "1000.00"),
        ("debit", "200.00"),
    ]
    assert client.get("/api/reports/trial-balance").json()["balanced"]
    assert client.get(f"/api/recurring/{created['id']}").json()["postings"][2]["side"] == "credit"


def test_a_split_rule_must_balance_and_not_mix_shapes(client, split_accounts):
    a = split_accounts
    unbalanced = {
        "postings": [
            {"category_id": a["rent"], "side": "debit", "amount": "1000"},
            {"account_id": a["bank"], "side": "credit", "amount": "900"},
        ],
        "start_date": "2999-01-01",
    }
    assert client.post("/api/recurring/", json=unbalanced).status_code == 400
    mixed = {**unbalanced, "from_account_id": a["bank"], "amount": "5"}
    assert client.post("/api/recurring/", json=mixed).status_code == 422
    assert client.post("/api/recurring/", json={"start_date": "2999-01-01"}).status_code == 422
    one = {"postings": unbalanced["postings"][:1], "start_date": "2999-01-01"}
    assert client.post("/api/recurring/", json=one).status_code == 422


def test_a_split_rule_can_be_edited_into_a_plain_one_and_back(client, split_accounts):
    a = split_accounts
    recurring_id = split_rule(client, a, start_date="2999-01-01")["id"]
    plain = {
        "from_account_id": a["bank"],
        "to_account_id": a["expenses"],
        "category_id": a["rent"],
        "amount": "1500",
        "start_date": "2999-01-01",
    }
    updated = client.put(f"/api/recurring/{recurring_id}", json=plain).json()
    assert updated["postings"] == [] and updated["amount"] == "1500.00"
    again = client.put(
        f"/api/recurring/{recurring_id}",
        json={
            "postings": [
                {"category_id": a["rent"], "side": "debit", "amount": "1"},
                {"category_id": a["Water"], "side": "debit", "amount": "2"},
                {"account_id": a["bank"], "side": "credit", "amount": "3"},
            ],
            "start_date": "2999-01-01",
        },
    ).json()
    assert len(again["postings"]) == 3 and again["from_account_id"] is None


def test_a_category_a_split_rule_uses_cannot_be_deleted(client, split_accounts):
    split_rule(client, split_accounts, start_date="2999-01-01")
    assert client.post(f"/api/categories/{split_accounts['Water']}/delete").status_code == 400


def test_deleting_a_split_rule_removes_its_rows(client, split_accounts, session):
    from finode.models.recurring import RecurringPosting

    recurring_id = split_rule(client, split_accounts, start_date="2999-01-01")["id"]
    assert len(session.exec(RecurringPosting.__table__.select()).all()) == 3
    assert client.delete(f"/api/recurring/{recurring_id}").status_code in (200, 204)
    assert session.exec(RecurringPosting.__table__.select()).all() == []


def test_assistants_see_split_rules(session, client, split_accounts):
    import asyncio

    from tests.mcputil import make_token, mcp_client, payload, running_app

    split_rule(client, split_accounts, start_date="2999-01-01")

    async def go():
        async with running_app(session), mcp_client(make_token(session, TEST_USER_ID)) as c:
            return payload(await c.call_tool("list_recurring", {}))["recurring"]

    [item] = asyncio.run(go())
    assert "from" not in item and len(item["postings"]) == 3
    assert {p["side"] for p in item["postings"]} == {"debit", "credit"} and item["postings"][0]["account"]
