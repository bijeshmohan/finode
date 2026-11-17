"""What is coming up: entries dated ahead and the occurrences rules will record are one list; the budget is as of today."""

from datetime import date

import pytest

from tests.books import leg, post_account
from tests.budget.test_recurring import accounts, rule  # noqa: F401  (fixtures and helpers)

FAKE_TODAY = date(2999, 11, 2)


def entry(client, accounts, on, payee="Shop", amount="100", **extra):
    body = {
        "date": str(on),
        "payee": payee,
        "postings": [
            leg({"id": accounts["expenses"]}, "debit", amount, category_id=accounts["rent"]),
            leg({"id": accounts["bank"]}, "credit", amount),
        ],
        **extra,
    }
    response = client.post("/api/transactions/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def coming(client, **params):
    response = client.get("/api/budget/coming-up", params=params)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def fake_today(monkeypatch):
    """A day far ahead, so nothing real is due: the entries and rules here are all dated after it."""
    monkeypatch.setattr("finode.services.coming_up.local_today", lambda: FAKE_TODAY)
    monkeypatch.setattr("finode.services.budget.local_today", lambda: FAKE_TODAY)
    return FAKE_TODAY


def test_an_entry_dated_ahead_and_a_rule_are_one_list_soonest_first(client, accounts, fake_today):
    entry(client, accounts, "2999-11-14", payee="Landlord Two", amount="30")
    rule(client, accounts, start_date="2999-11-10", payee="Landlord", amount="1500")
    entry(client, accounts, "2999-11-03", payee="Cab", amount="70")
    found = coming(client, through="2999-11-30")
    assert [(i["date"], i["payee"], i["amount"]) for i in found["items"]] == [
        ("2999-11-03", "Cab", "70.00"),
        ("2999-11-10", "Landlord", "1500.00"),
        ("2999-11-14", "Landlord Two", "30.00"),
    ]
    cab, landlord, _ = found["items"]
    assert cab["transaction_id"] and cab["recurring_id"] is None, "recorded: an entry"
    assert landlord["recurring_id"] and landlord["transaction_id"] is None, "a rule: not recorded yet"
    assert found["count"] == 3 and found["total"] == "1600.00"
    assert found["through"] == "2999-11-30"


def test_it_ends_at_the_end_of_this_month_unless_asked(client, accounts, fake_today):
    entry(client, accounts, "2999-11-20", payee="This month")
    entry(client, accounts, "2999-12-05", payee="Next month")
    assert [i["payee"] for i in coming(client)["items"]] == ["This month"]
    assert coming(client)["through"] == "2999-11-30"
    assert [i["payee"] for i in coming(client, through="2999-12-31")["items"]] == ["This month", "Next month"]


def test_a_monthly_rule_shows_once_and_a_weekly_one_each_time_it_falls_due(client, accounts, fake_today):
    rule(client, accounts, start_date="2999-11-05", payee="Rent")
    rule(client, accounts, start_date="2999-11-03", frequency="weekly", payee="Weekly", amount="10")
    days = [(i["date"], i["payee"]) for i in coming(client)["items"]]
    assert days == [
        ("2999-11-03", "Weekly"),
        ("2999-11-05", "Rent"),
        ("2999-11-10", "Weekly"),
        ("2999-11-17", "Weekly"),
        ("2999-11-24", "Weekly"),
    ]


def test_a_rule_that_is_behind_shows_on_the_days_it_falls_due_not_tomorrow(client, accounts, fake_today):
    """An occurrence that fell due and is not recorded yet (the catch-up has not run, or a problem holds it) is not
    coming up: the next ones are, on the rule's own days."""
    rule(client, accounts, start_date="2999-10-28", payee="Rent")
    rule(client, accounts, start_date="2999-10-20", frequency="weekly", payee="Weekly", amount="10")
    assert [(i["date"], i["payee"]) for i in coming(client)["items"]] == [
        ("2999-11-03", "Weekly"),
        ("2999-11-10", "Weekly"),
        ("2999-11-17", "Weekly"),
        ("2999-11-24", "Weekly"),
        ("2999-11-28", "Rent"),
    ]


def test_a_paused_or_ended_rule_is_not_coming_up(client, accounts, fake_today):
    paused = rule(client, accounts, start_date="2999-11-05", payee="Paused")
    assert client.post(f"/api/recurring/{paused['id']}/pause").status_code == 200
    rule(client, accounts, start_date="2999-11-05", end_date="2999-11-06", frequency="daily", payee="Short", amount="5")
    assert [(i["date"], i["payee"]) for i in coming(client)["items"]] == [
        ("2999-11-05", "Short"),
        ("2999-11-06", "Short"),
    ]


def test_only_what_touches_the_budget_is_listed(client, accounts, root_accounts, fake_today):
    outside = post_account(
        client, {"name": "House fund", "parent_id": root_accounts["Assets"], "on_budget": False, "balance": "500"}
    ).json()
    other = post_account(client, {"name": "Locker", "parent_id": root_accounts["Assets"], "on_budget": False}).json()
    moved = client.post(
        "/api/transactions/",
        json={
            "date": "2999-11-09",
            "payee": "Between",
            "postings": [leg(other, "debit", "50"), leg(outside, "credit", "50")],
        },
    )
    assert moved.status_code == 201, moved.text
    entry(client, accounts, "2999-11-08", payee="Counted")
    assert [i["payee"] for i in coming(client)["items"]] == ["Counted"]


def test_money_in_is_marked_and_a_mixed_list_has_no_total(client, accounts, root_accounts, fake_today):
    salary = client.post("/api/categories/", json={"name": "Pay", "kind": "earning"}).json()
    paid = client.post(
        "/api/transactions/",
        json={
            "date": "2999-11-04",
            "payee": "Employer",
            "postings": [
                leg({"id": accounts["bank"]}, "debit", "900"),
                leg({"id": root_accounts["Income"]}, "credit", "900", category_id=salary["id"]),
            ],
        },
    )
    assert paid.status_code == 201, paid.text
    only_in = coming(client)
    assert [(i["income"], i["amount"]) for i in only_in["items"]] == [(True, "900.00")] and only_in["total"] == "900.00"
    entry(client, accounts, "2999-11-06", amount="40")
    mixed = coming(client)
    assert [i["income"] for i in mixed["items"]] == [True, False] and mixed["total"] is None


def test_looking_more_than_a_year_ahead_is_refused(client, accounts, monkeypatch):
    monkeypatch.setattr("finode.services.coming_up.local_today", lambda: date(2998, 1, 1))
    assert client.get("/api/budget/coming-up", params={"through": "2998-12-31"}).status_code == 200
    assert client.get("/api/budget/coming-up", params={"through": "2999-01-05"}).status_code == 400


def test_nothing_coming_up_is_an_empty_list(client, accounts, fake_today):
    assert coming(client) == {"through": "2999-11-30", "count": 0, "total": None, "items": []}


def test_the_budget_is_as_of_today_and_a_later_month_counts_what_is_dated_in_the_one_before(
    client, accounts, root_accounts, fake_today
):
    entry(client, accounts, "2999-11-10", amount="100")
    now = client.get("/api/budget/").json()
    assert now["month"] == "2999-11-01"
    assert now["money_in_accounts"] == "10000.00" and now["activity"] == "0.00", "nothing dated ahead is in yet"
    later = client.get("/api/budget/", params={"month": "2999-12-01"}).json()
    assert later["money_in_accounts"] == "9900.00", "by December it has happened"


def test_the_list_counts_them_and_says_what_they_come_to(client, accounts, fake_today):
    entry(client, accounts, "2999-11-10", payee="Cab", amount="70")
    one = client.get("/api/views/coming-up", params={"through": "2999-11-30"}).json()
    assert one["count"] == 1
    rule(client, accounts, start_date="2999-11-12", payee="Landlord", amount="1500")
    seen = client.get("/api/views/coming-up", params={"through": "2999-11-30"}).json()
    assert (seen["count"], seen["total"]) == (2, "1570.00"), "the entry and the rule, both going out"
    marked = {r["title"]: r["recurring_id"] is not None for d in seen["days"] for r in d["rows"]}
    assert marked == {"Cab": False, "Landlord": True}, "only the rule repeats"
