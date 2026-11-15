"""/api/views/todo, /api/views/coming-up and /api/views/recurring: what the to-do bell's sheet, the Coming up list and
the Recurring list show in the finode app, worked out as the web pages work it out (services/coming_up_view.py,
services/recurring_view.py), and the bell's one fix with no route of its own before: giving a payment a category."""

from datetime import date
from uuid import UUID

from sqlmodel import select

from app.models.recurring import RecurringTransaction

from .books import leg, post_account
from .test_budget import account, move
from .test_budget_categories import books, paid  # noqa: F401  # books is a fixture
from .test_coming_up import entry, fake_today  # noqa: F401  # fake_today is a fixture
from .test_isolation import B_USER, signed_in_as
from .test_recurring import accounts, rule, split_accounts, split_rule  # noqa: F401  # fixtures
from .test_todo_card_bills import card_with_bill


def view(client, path, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---- the bell ---------------------------------------------------------------------------------------------------


def test_the_todo_view_counts_and_lists_what_needs_you(client, books, root_accounts, expense_account):
    made = paid(client, books["bank"], books["loan"], "19277")
    card = account(client, root_accounts, "Card", "Liabilities")
    food = account(client, root_accounts, "Food", "Expenses")
    move(client, card, food, "75")
    visa = card_with_bill(client, root_accounts, expense_account, due_in=2)
    seen = view(client, "/api/views/todo")
    assert [(u["transaction_id"], u["amount"], u["account"]) for u in seen["uncategorised"]] == [
        (made["id"], "19277.00", "Liabilities:Home Loan")
    ]
    left = {a["path"]: a for a in seen["left_out_accounts"]}
    assert left["Liabilities:Card"]["spent"] == "75.00" and left["Liabilities:Card"]["entries"] == 1
    assert [(b["account_id"], b["name"], b["bill"], b["days_to_due"]) for b in seen["card_bills"]] == [
        (visa["id"], "Visa", "1250.00", 2)
    ]
    assert seen["count"] == client.get("/api/todo/").json()["count"]
    paths = [c["path"] for c in seen["categories"]]
    assert {"EMI", "SIP", "Food"} <= set(paths) and all(c["id"] for c in seen["categories"])


def test_a_failing_rule_is_in_the_todo_view(client, accounts, session):
    made = rule(client, accounts, start_date="2999-01-01")
    found = session.exec(select(RecurringTransaction).where(RecurringTransaction.id == UUID(made["id"]))).one()
    found.last_error = "Bank can no longer be posted to"
    session.add(found)
    session.commit()
    seen = view(client, "/api/views/todo")
    assert seen["failing_rules"] == [
        {"recurring_id": made["id"], "name": "Landlord", "error": "Bank can no longer be posted to"}
    ]


def test_labelling_a_payment_takes_it_off_the_list(client, books):
    made = paid(client, books["bank"], books["loan"], "19277")
    before = view(client, "/api/views/todo")["count"]
    labelled = client.post(f"/api/transactions/{made['id']}/category", json={"category_id": books["emi"]["id"]})
    assert labelled.status_code == 200, labelled.text
    assert {p["category_id"] for p in labelled.json()["postings"]} == {None, books["emi"]["id"]}
    seen = view(client, "/api/views/todo")
    assert seen["count"] == before - 1 and seen["uncategorised"] == []
    again = client.post(f"/api/transactions/{made['id']}/category", json={"category_id": books["sip"]["id"]})
    assert again.status_code == 400 and "no payment waiting" in again.json()["detail"]
    missing = client.post(
        "/api/transactions/00000000-0000-4000-8000-0000000000aa/category", json={"category_id": books["sip"]["id"]}
    )
    assert missing.status_code == 404
    with signed_in_as(B_USER):
        stranger = client.post(f"/api/transactions/{made['id']}/category", json={"category_id": books["sip"]["id"]})
        assert stranger.status_code == 404
        assert view(client, "/api/views/todo")["count"] == 0


# ---- Coming up --------------------------------------------------------------------------------------------------


def test_coming_up_days(client, accounts, root_accounts, fake_today):
    salary = post_account(client, {"name": "Salary", "parent_id": root_accounts["Income"]}).json()["id"]
    entry(client, accounts, "2999-11-05", payee="Cab", amount="70")
    entry(client, accounts, "2999-11-05", payee="Lunch", amount="30")
    entry(client, accounts, "2999-11-07", payee="Cinema", amount="20")
    rule(client, accounts, start_date="2999-11-09", payee="Landlord", amount="1500")
    entry(client, accounts, "2999-11-09", payee="Cab", amount="10")
    pay = {
        "date": "2999-11-12",
        "payee": "Work",
        "postings": [
            leg({"id": accounts["bank"]}, "debit", "500"),
            leg({"id": root_accounts["Income"]}, "credit", "500", category_id=salary),
        ],
    }
    assert client.post("/api/transactions/", json=pay).status_code == 201
    seen = view(client, "/api/views/coming-up", through="2999-11-30")
    assert seen["through"] == "2999-11-30" and seen["count"] == 6
    days = {d["date"]: d for d in seen["days"]}
    assert days["2999-11-05"]["total"] == "100.00", "two payments one way: the day adds up"
    assert days["2999-11-07"]["total"] is None, "one row: no total"
    assert days["2999-11-09"]["total"] == "1510.00", "a rule and an entry, both spending"
    payday = days["2999-11-12"]["rows"][0]
    assert payday["income"] is True and payday["title"] == "Work"
    rows = days["2999-11-09"]["rows"]
    by_title = {r["title"]: r for r in rows}
    assert by_title["Landlord"]["recurring_id"] and by_title["Landlord"]["transaction_id"] is None
    assert by_title["Cab"]["transaction_id"] and by_title["Cab"]["recurring_id"] is None
    assert by_title["Cab"]["sub"] == "Bank → Rent"


def test_a_mixed_day_has_no_total(client, accounts, root_accounts, fake_today):
    salary = post_account(client, {"name": "Salary", "parent_id": root_accounts["Income"]}).json()["id"]
    entry(client, accounts, "2999-11-05", payee="Cab", amount="70")
    pay = {
        "date": "2999-11-05",
        "payee": "Work",
        "postings": [
            leg({"id": accounts["bank"]}, "debit", "500"),
            leg({"id": root_accounts["Income"]}, "credit", "500", category_id=salary),
        ],
    }
    assert client.post("/api/transactions/", json=pay).status_code == 201
    (day,) = view(client, "/api/views/coming-up", through="2999-11-30")["days"]
    assert day["total"] is None and len(day["rows"]) == 2


def test_nothing_coming_up(client, accounts, fake_today):
    seen = view(client, "/api/views/coming-up")
    assert seen["count"] == 0 and seen["days"] == [] and seen["through"]


# ---- the Recurring list ----------------------------------------------------------------------------------------


def test_the_recurring_view(client, split_accounts, session):
    a = split_accounts
    later = rule(client, a, start_date="2999-01-01", payee="Landlord")
    nameless = rule(client, a, start_date="2999-02-01", payee="")
    paused = rule(client, a, start_date="2999-03-01", payee="Gym")
    assert client.post(f"/api/recurring/{paused['id']}/pause").status_code == 200
    ended = rule(client, a, start_date="2026-01-01", end_date="2026-02-15", payee="Course")
    split = split_rule(client, a, start_date="2999-04-01", payee="Bills")
    failing = rule(client, a, start_date="2999-05-01", payee="Broken")
    found = session.exec(select(RecurringTransaction).where(RecurringTransaction.id == UUID(failing["id"]))).one()
    found.last_error = "Bank can no longer be posted to"
    session.add(found)
    session.commit()
    seen = view(client, "/api/views/recurring")
    live = {r["id"]: r for r in seen["live"]}
    stopped = {r["id"]: r for r in seen["stopped"]}
    assert set(live) == {later["id"], nameless["id"], split["id"], failing["id"]}
    assert set(stopped) == {paused["id"], ended["id"]}
    assert (live[later["id"]]["title"], live[later["id"]]["amount"], live[later["id"]]["status"]) == (
        "Landlord",
        "1500.00",
        "active",
    )
    assert live[later["id"]]["schedule"] == "Every month" and live[later["id"]]["next_date"] == "2999-01-01"
    assert live[nameless["id"]]["title"] == "Expenses › Rent", "no payee: the To name, as the web page reads it"
    assert live[split["id"]]["amount"] == "1200.00", "a split: what leaves"
    assert live[failing["id"]]["status"] == "error"
    assert live[failing["id"]]["last_error"] == "Bank can no longer be posted to"
    assert stopped[paused["id"]]["status"] == "paused" and stopped[ended["id"]]["status"] == "ended"


def test_strangers_see_none_of_it(client, accounts, fake_today):
    rule(client, accounts, start_date="2999-11-09")
    with signed_in_as(B_USER):
        assert view(client, "/api/views/recurring") == {"live": [], "stopped": []}
        assert view(client, "/api/views/coming-up")["days"] == []
        assert view(client, "/api/views/todo")["count"] == 0
    assert date.fromisoformat(view(client, "/api/views/recurring")["live"][0]["next_date"])


def test_coming_up_more_than_a_year_ahead_is_refused(client, accounts):
    too_far = client.get("/api/views/coming-up", params={"through": "2999-12-31"})
    assert too_far.status_code == 400 and "366 days ahead" in too_far.json()["detail"]
