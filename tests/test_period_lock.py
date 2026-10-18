"""The period lock: the books are closed up to a day; nothing dated in it can change."""

from contextlib import nullcontext
from datetime import date, timedelta

import pytest

from app.clock import local_today

from .test_budget import move_budget, press

TODAY = local_today()
YESTERDAY = TODAY - timedelta(days=1)
LAST_MONTH_END = TODAY.replace(day=1) - timedelta(days=1)
LAST_MONTH = LAST_MONTH_END.replace(day=1)


@pytest.fixture
def books(client, root_accounts):
    def make(name, root, **extra):
        response = client.post("/api/accounts/", json={"name": name, "parent_id": root_accounts[root], **extra})
        assert response.status_code == 201, response.text
        return response.json()

    return {"bank": make("Bank", "Assets", balance="5000"), "food": make("Food", "Expenses"), "rent": make("Rent", "Expenses")}


def entry(client, books, when, amount="10", category="food", **extra):
    return client.post("/api/transactions/", json={
        "date": when.isoformat(),
        "postings": [
            {"account": books[category]["aid"], "side": "debit", "amount": amount},
            {"account": books["bank"]["aid"], "side": "credit", "amount": amount},
        ],
        **extra,
    })


def lock(client, day):
    response = client.patch("/api/profile/", json={"locked_through": day.isoformat() if day else None})
    assert response.status_code == 200, response.text
    return response.json()


# ---- setting the lock ----------------------------------------------------------------------------------------------


def test_the_lock_is_set_read_and_removed(client):
    assert client.get("/api/profile/").json()["locked_through"] is None
    assert lock(client, LAST_MONTH_END)["locked_through"] == LAST_MONTH_END.isoformat()
    assert client.get("/api/profile/").json()["locked_through"] == LAST_MONTH_END.isoformat()
    assert lock(client, None)["locked_through"] is None
    assert client.patch("/api/profile/", json={"first_name": "Asha"}).json()["locked_through"] is None  # other edits leave it be
    lock(client, YESTERDAY)
    assert client.patch("/api/profile/", json={"first_name": "Asha"}).json()["locked_through"] == YESTERDAY.isoformat()


def test_today_and_the_future_cannot_be_locked(client):
    for day in (TODAY, TODAY + timedelta(days=30)):
        response = client.patch("/api/profile/", json={"locked_through": day.isoformat()})
        assert response.status_code == 400 and "yesterday" in response.json()["detail"]
    assert client.get("/api/profile/").json()["locked_through"] is None


# ---- the ledger ----------------------------------------------------------------------------------------------------


def test_entries_in_the_locked_period_cannot_be_added(client, books):
    lock(client, LAST_MONTH_END)
    refused = entry(client, books, LAST_MONTH_END)
    assert refused.status_code == 400 and "locked period" in refused.json()["detail"]
    assert str(LAST_MONTH_END.year) in refused.json()["detail"]
    assert entry(client, books, LAST_MONTH_END + timedelta(days=1)).status_code == 201
    assert entry(client, books, TODAY).status_code == 201


def test_without_a_date_today_is_used_and_is_open(client, books):
    lock(client, YESTERDAY)
    made = client.post("/api/transactions/", json={"postings": [
        {"account": books["food"]["aid"], "side": "debit", "amount": "5"},
        {"account": books["bank"]["aid"], "side": "credit", "amount": "5"}]})
    assert made.status_code == 201


def test_entries_in_it_cannot_be_changed_moved_in_or_out_or_deleted(client, books):
    old = entry(client, books, LAST_MONTH_END - timedelta(days=3)).json()
    open_one = entry(client, books, TODAY).json()
    lock(client, LAST_MONTH_END)
    for change in ({"payee": "edited"}, {"date": TODAY.isoformat()}):
        refused = client.patch(f"/api/transactions/{old['tid']}", json=change)
        assert refused.status_code == 400 and "locked period" in refused.json()["detail"], change
    moved_in = client.patch(f"/api/transactions/{open_one['tid']}", json={"date": LAST_MONTH.isoformat()})
    assert moved_in.status_code == 400
    deleted = client.delete(f"/api/transactions/{old['tid']}")
    assert deleted.status_code == 400 and "locked period" in deleted.json()["detail"]
    assert client.get(f"/api/transactions/{old['tid']}").json()["payee"] is None, "nothing changed"
    # the open one can still be edited and deleted
    assert client.patch(f"/api/transactions/{open_one['tid']}", json={"payee": "fine"}).status_code == 200
    assert client.delete(f"/api/transactions/{open_one['tid']}").status_code == 204


def test_removing_the_lock_allows_a_correction(client, books):
    old = entry(client, books, LAST_MONTH_END - timedelta(days=3)).json()
    lock(client, LAST_MONTH_END)
    assert client.patch(f"/api/transactions/{old['tid']}", json={"payee": "x"}).status_code == 400
    lock(client, None)
    assert client.patch(f"/api/transactions/{old['tid']}", json={"payee": "x"}).status_code == 200


def test_balances_and_opening_balances_still_work(client, books, root_accounts):
    lock(client, YESTERDAY)
    made = client.post("/api/accounts/", json={"name": "Cash", "parent_id": root_accounts["Assets"], "balance": "100"})
    assert made.status_code == 201
    assert client.patch(f"/api/accounts/{made.json()['aid']}", json={"balance": "150"}).status_code == 200


# ---- the web forms -------------------------------------------------------------------------------------------------


def test_the_form_says_why(client, books):
    lock(client, LAST_MONTH_END)
    bad = client.post("/transactions/split", data={
        "date": LAST_MONTH_END.isoformat(), "account": [books["food"]["aid"], books["bank"]["aid"]],
        "side": ["debit", "credit"], "amount": ["5", "5"]})
    assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#form-error" and "locked period" in bad.text


def test_an_entry_in_the_period_opens_with_a_notice_and_no_buttons(client, books):
    old = entry(client, books, LAST_MONTH_END - timedelta(days=2)).json()
    open_one = entry(client, books, TODAY).json()
    lock(client, LAST_MONTH_END)
    page = client.get(f"/transactions/{old['tid']}/edit").text
    assert "This entry is in a locked period" in page and 'type="submit" disabled' in page and 'class="danger" disabled' in page
    page = client.get(f"/transactions/{open_one['tid']}/edit").text
    assert "locked period" not in page and "disabled" not in page.split('<form')[1].split('</form>')[0]
    refused = client.post(f"/transactions/{old['tid']}/delete")
    assert refused.status_code == 400 and refused.headers["HX-Retarget"] == "#page-error"


def test_the_settings_page_sets_and_removes_it(client):
    page = client.get("/settings/advanced").text
    assert 'id="lock"' in page and "Period lock" in page and "off" in page
    saved = client.post("/settings/lock", data={"locked_through": LAST_MONTH_END.isoformat()})
    assert saved.status_code == 200 and "lock-saved" in saved.headers["set-cookie"]
    assert LAST_MONTH_END.strftime("up to %d %b %Y") in client.get("/settings/advanced").text
    removed = client.post("/settings/lock", data={"locked_through": ""})
    assert "lock-removed" in removed.headers["set-cookie"] and client.get("/api/profile/").json()["locked_through"] is None


def test_the_settings_form_reports_problems(client):
    for bad in ("not a date", TODAY.isoformat()):
        response = client.post("/settings/lock", data={"locked_through": bad})
        assert response.status_code == 400 and response.headers["HX-Retarget"] == "#lock-error", bad


# ---- the budget ----------------------------------------------------------------------------------------------------


def assign(client, books, month, amount="100"):
    return client.put(f"/api/budget/categories/{books['food']['aid']}", json={"month": month.isoformat(), "amount": amount})


def test_a_closed_months_budget_is_frozen(client, books):
    assert assign(client, books, LAST_MONTH, "50").status_code == 200
    lock(client, LAST_MONTH_END)
    refused = assign(client, books, LAST_MONTH, "70")
    assert refused.status_code == 400 and "locked period" in refused.json()["detail"]
    assert assign(client, books, TODAY.replace(day=1), "70").status_code == 200
    assert move_budget(client, books["food"], books["rent"], "5", LAST_MONTH).status_code == 400
    assert press(client, "copy", LAST_MONTH).status_code == 400
    assert press(client, "fund", LAST_MONTH).status_code == 400


def test_a_month_only_part_of_which_is_locked_is_still_open(client, books):
    middle = LAST_MONTH + timedelta(days=9)
    lock(client, middle)
    assert assign(client, books, LAST_MONTH, "70").status_code == 200, "the month does not end inside the lock"
    lock(client, LAST_MONTH_END)
    assert assign(client, books, LAST_MONTH, "80").status_code == 400, "now it does"


def test_the_budget_page_says_so(client, books):
    lock(client, LAST_MONTH_END)
    bad = client.post("/budget/assign", data={"category": books["food"]["aid"], "month": LAST_MONTH.strftime("%Y-%m"), "amount": "5"})
    assert bad.status_code == 400 and "locked period" in bad.text


# ---- recurring rules -----------------------------------------------------------------------------------------------


def test_occurrences_in_the_locked_period_are_left_out(client, books, session, monkeypatch):
    from app.mcp_server import context
    from app.models.recurring import RecurringTransaction
    from app.models.transaction import Transaction
    from app.recurring_runner import run_once

    monkeypatch.setattr(context, "session_factory", lambda: nullcontext(session))
    start = TODAY - timedelta(days=3)
    created = client.post("/api/recurring/", json={
        "from_account": books["bank"]["aid"], "to_account": books["food"]["aid"], "amount": "10", "frequency": "daily",
        "start_date": (TODAY + timedelta(days=30)).isoformat()})
    assert created.status_code == 201
    rid = created.json()["rid"]
    # make it as if it started three days ago, then close the books up to yesterday
    session.exec(RecurringTransaction.__table__.update().values(start_date=start, next_date=start))
    session.commit()
    lock(client, YESTERDAY)
    assert run_once(TODAY) == 1, "only today is open"
    days = sorted(t.date for t in session.exec(Transaction.__table__.select().where(Transaction.created_via == "recurring")).all())
    assert days == [TODAY]
    rule = client.get(f"/api/recurring/{rid}").json()
    assert rule["skipped_date"] == YESTERDAY.isoformat() and rule["last_date"] == TODAY.isoformat()
    assert rule["last_error"] is None and rule["active"] is True


# ---- erase and backup ----------------------------------------------------------------------------------------------


def test_erasing_the_books_removes_the_lock(client, books, root_accounts):
    lock(client, LAST_MONTH_END)
    response = client.post("/profile/data/erase", data={"confirm": "test@example.com"})
    assert response.status_code == 200, response.text
    assert client.get("/api/profile/").json()["locked_through"] is None
    roots = {a["name"]: a["aid"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}  # made again, new ids
    fresh = {
        "bank": client.post("/api/accounts/", json={"name": "Bank", "parent_id": roots["Assets"]}).json(),
        "food": client.post("/api/accounts/", json={"name": "Food", "parent_id": roots["Expenses"]}).json(),
    }
    assert entry(client, fresh, LAST_MONTH_END - timedelta(days=5)).status_code == 201, "the old period is open again"
