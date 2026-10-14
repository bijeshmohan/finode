"""Weekly targets: the month week by week, with what was spent in each."""

from datetime import date, timedelta

import pytest

from app.clock import local_today
from app.services.budget import weeks_of

from .test_budget import account, assign, budget, line, target

TODAY = local_today()
THIS_MONTH = TODAY.replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


# ---- the arithmetic ------------------------------------------------------------------------------------------------


def test_a_month_cut_into_weeks_starting_on_a_day():
    # October 2026 starts on a Thursday; weeks that start on Fridays: 2, 9, 16, 23, 30
    weeks = weeks_of(date(2026, 10, 1), 4)
    assert weeks[0] == (date(2026, 10, 1), date(2026, 10, 1), False), "Thursday the 1st belongs to last month's week"
    assert [(a.day, b.day, funded) for a, b, funded in weeks[1:]] == [
        (2, 8, True), (9, 15, True), (16, 22, True), (23, 29, True), (30, 31, True)
    ]
    assert len([w for w in weeks if w[2]]) == 5, "as many funded weeks as Fridays in the month"


def test_when_the_month_starts_on_that_day_every_week_is_funded():
    weeks = weeks_of(date(2026, 10, 1), 3)  # Thursdays
    assert weeks[0] == (date(2026, 10, 1), date(2026, 10, 7), True) and all(w[2] for w in weeks)
    assert weeks[-1] == (date(2026, 10, 29), date(2026, 10, 31), True), "the last week stops at the month's end"


def test_the_weeks_cover_the_month_exactly_once():
    for month in (date(2026, 2, 1), date(2028, 2, 1), date(2026, 12, 1), date(2026, 10, 1)):
        for weekday in range(7):
            weeks = weeks_of(month, weekday)
            days = [w[0] + timedelta(days=i) for w in weeks for i in range((w[1] - w[0]).days + 1)]
            assert days == sorted(set(days)) and days[0] == month and days[-1].month == month.month
            assert sum(1 for w in weeks if w[2]) == sum(1 for d in days if d.weekday() == weekday)


# ---- in the budget -------------------------------------------------------------------------------------------------


@pytest.fixture
def setup(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="5000")
    food = account(client, root_accounts, "Food", "Expenses")
    rent = account(client, root_accounts, "Rent", "Expenses")
    return {"bank": bank, "food": food, "rent": rent}


def spend(client, setup, when, amount, category="food"):
    response = client.post("/api/transactions/", json={
        "date": when.isoformat(),
        "postings": [
            {"account": setup[category]["aid"], "side": "debit", "amount": amount},
            {"account": setup["bank"]["aid"], "side": "credit", "amount": amount},
        ]})
    assert response.status_code == 201, response.text


def test_a_weekly_target_lists_its_weeks_with_what_was_spent(client, setup):
    weekday = THIS_MONTH.weekday()  # weeks start on the 1st: simple to reason about
    assign(client, setup["food"], "300")
    target(client, setup["food"], "weekly", "100", weekday=weekday)
    spend(client, setup, THIS_MONTH, "40")
    spend(client, setup, THIS_MONTH + timedelta(days=3), "30")
    spend(client, setup, THIS_MONTH + timedelta(days=8), "130")
    weeks = line(budget(client), "Food")["weeks"]
    assert weeks[0]["start"] == THIS_MONTH.isoformat() and weeks[0]["spent"] == "70.00" and weeks[0]["allowance"] == "100.00"
    assert weeks[1]["start"] == (THIS_MONTH + timedelta(days=7)).isoformat() and weeks[1]["spent"] == "130.00"
    assert sum(float(w["spent"]) for w in weeks) == float(line(budget(client), "Food")["activity"]) == 200.0


def test_the_days_before_the_first_such_day_are_a_week_funded_last_month(client, setup):
    weekday = (THIS_MONTH.weekday() + 2) % 7
    target(client, setup["food"], "weekly", "100", weekday=weekday)
    spend(client, setup, THIS_MONTH, "25")
    first = line(budget(client), "Food")["weeks"][0]
    assert first["start"] == THIS_MONTH.isoformat() and first["allowance"] is None and first["spent"] == "25.00"
    assert line(budget(client), "Food")["weeks"][1]["allowance"] == "100.00"


def test_only_the_selected_months_spending_counts(client, setup):
    target(client, setup["food"], "weekly", "100", weekday=THIS_MONTH.weekday())
    spend(client, setup, LAST_MONTH + timedelta(days=2), "999")
    assert all(w["spent"] == "0.00" for w in line(budget(client), "Food")["weeks"])
    earlier = line(budget(client, LAST_MONTH), "Food")["weeks"]
    assert earlier[0]["start"] == LAST_MONTH.isoformat() and earlier[-1]["end"] == (THIS_MONTH - timedelta(days=1)).isoformat()
    assert sum(float(w["spent"]) for w in earlier) == 999.0


def test_the_current_week_is_marked(client, setup):
    target(client, setup["food"], "weekly", "100", weekday=TODAY.weekday())
    weeks = line(budget(client), "Food")["weeks"]
    assert [w["start"] for w in weeks if w["current"]] == [TODAY.isoformat()]
    assert sum(1 for w in line(budget(client, LAST_MONTH), "Food")["weeks"] if w["current"]) == 0


def test_other_targets_and_groups_have_no_weeks(client, setup):
    target(client, setup["food"], "monthly", "300")
    assert line(budget(client), "Food")["weeks"] == []
    assert line(budget(client), "Rent")["weeks"] == []
    target(client, setup["rent"], "weekly", "10", weekday=0)
    child = client.post("/api/accounts/", json={"name": "Dining", "parent_id": setup["food"]["aid"]}).json()
    target(client, child, "weekly", "50", weekday=0)
    data = budget(client)
    assert line(data, "Dining")["weeks"] and line(data, "Food")["weeks"] == [], "a group has none of its own"


def test_removing_the_target_removes_the_weeks(client, setup):
    target(client, setup["food"], "weekly", "100", weekday=0)
    assert line(budget(client), "Food")["weeks"]
    client.delete(f"/api/budget/categories/{setup['food']['aid']}/target")
    assert line(budget(client), "Food")["weeks"] == []


# ---- the page ------------------------------------------------------------------------------------------------------


def squash(text):
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


def test_the_page_shows_the_weeks_and_marks_an_overspent_one(client, setup):
    assign(client, setup["food"], "300")
    client.post("/budget/target", data={"category": setup["food"]["aid"], "kind": "weekly", "amount": "100", "weekday": str(THIS_MONTH.weekday())})
    spend(client, setup, THIS_MONTH, "130")
    page = client.get("/budget").text
    assert 'class="weeks"' in page and "By week" in page
    text = squash(page)
    assert "130.00 of 100.00" in text and "0.00 of 100.00" in text
    import re

    assert len(re.findall(r'<li class="[^"]*\bover\b[^"]*">', page)) == 1, "only the week that went over 100 is marked"


def test_a_category_without_a_weekly_target_has_no_week_list(client, setup):
    client.post("/budget/target", data={"category": setup["food"]["aid"], "kind": "monthly", "amount": "100"})
    assert 'class="weeks"' not in client.get("/budget").text
