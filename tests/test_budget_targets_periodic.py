"""Weekly and yearly budget targets, and the overdue mark on a by-a-month target that fell behind."""

from datetime import date
from decimal import Decimal

import pytest

from app.models.budget import BudgetTarget
from app.services.budget import due_month, funding, is_overdue, weekday_count

from .test_budget import THIS_MONTH, assign, budget, fixture_budget, line, target


def add_months(day: date, n: int) -> date:
    index = day.year * 12 + day.month - 1 + n
    return date(index // 12, index % 12 + 1, 1)


def row(kind, amount="100", **extra):
    return BudgetTarget(user=None, account_id=None, kind=kind, amount=Decimal(amount), **extra)


# ---- the arithmetic ------------------------------------------------------------------------------------------------


def test_counting_the_days_of_the_week_in_a_month():
    october = date(2026, 10, 1)  # a Thursday: Thursdays, Fridays and Saturdays come five times
    assert [weekday_count(october, d) for d in range(7)] == [4, 4, 4, 5, 5, 5, 4]
    assert weekday_count(date(2026, 2, 1), 0) == 4 and weekday_count(date(2024, 2, 1), 3) == 5  # a leap year


def test_a_weekly_target_needs_the_amount_for_each_such_day():
    mondays = row("weekly", "250", weekday=0)
    assert funding(mondays, Decimal(0), Decimal(0), date(2026, 10, 1), 2) == (Decimal("1000.00"), Decimal("1000.00"))
    thursdays = row("weekly", "250", weekday=3)
    assert funding(thursdays, Decimal(400), Decimal(0), date(2026, 10, 1), 2) == (Decimal("1250.00"), Decimal("850.00"))
    # what carried in does not change it: like a monthly target it is about assigning
    assert funding(thursdays, Decimal(0), Decimal(5000), date(2026, 10, 1), 2)[0] == Decimal("1250.00")


def test_a_yearly_target_rolls_on_to_next_year():
    june = row("yearly", target_date=date(2020, 6, 1))
    assert due_month(june, date(2026, 3, 1)) == date(2026, 6, 1)
    assert due_month(june, date(2026, 6, 1)) == date(2026, 6, 1)  # the month it falls due is still that cycle
    assert due_month(june, date(2026, 7, 1)) == date(2027, 6, 1)
    assert due_month(row("by_date", target_date=date(2026, 6, 1)), date(2026, 7, 1)) == date(2026, 6, 1)  # by_date does not roll


def test_a_yearly_target_saves_evenly_then_starts_over():
    twelve = row("yearly", "1200", target_date=date(2020, 6, 1))
    needed = lambda month, carried="0": funding(twelve, Decimal(0), Decimal(carried), month, 2)[0]
    assert needed(date(2026, 3, 1)) == Decimal("300.00")  # March, April, May and June are left
    assert needed(date(2026, 6, 1)) == Decimal("1200.00")  # the whole rest in the month it falls due
    assert needed(date(2026, 6, 1), "900") == Decimal("300.00")
    assert needed(date(2026, 7, 1)) == Decimal("100.00")  # paid in June: twelve months to the next one


def test_only_a_by_date_target_that_fell_behind_is_overdue():
    by = row("by_date", target_date=date(2026, 8, 1))
    assert is_overdue(by, date(2026, 9, 1), Decimal(50)) is True
    assert is_overdue(by, date(2026, 8, 1), Decimal(50)) is False  # its own month is not late yet
    assert is_overdue(by, date(2026, 9, 1), Decimal(0)) is False  # funded
    assert is_overdue(row("yearly", target_date=date(2026, 8, 1)), date(2026, 9, 1), Decimal(50)) is False
    assert is_overdue(row("monthly"), date(2026, 9, 1), Decimal(50)) is False


# ---- through the API -----------------------------------------------------------------------------------------------


def test_weekly_target(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    data = target(client, food, "weekly", "100", weekday=THIS_MONTH.weekday())
    mine = line(data, "Food")
    assert mine["target"] == {"kind": "weekly", "amount": "100.00", "target_date": None, "weekday": THIS_MONTH.weekday()}
    assert mine["needed"] == f"{100 * weekday_count(THIS_MONTH, THIS_MONTH.weekday())}.00" and mine["overdue"] is False
    assign(client, food, mine["needed"])
    assert line(budget(client), "Food")["underfunded"] == "0.00"


def test_yearly_target(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    due = add_months(THIS_MONTH, 3)
    data = target(client, rent, "yearly", "1200", target_date=date(2019, due.month, 17).isoformat())  # the year and day do not matter
    assert line(data, "Rent")["needed"] == "300.00"
    assert line(data, "Rent")["target"]["target_date"] == f"2019-{due.month:02d}-01"
    # the month it fell due last year is nearly a year away
    behind = add_months(THIS_MONTH, -1)
    data = target(client, rent, "yearly", "1200", target_date=behind.isoformat())
    assert line(data, "Rent")["needed"] == "100.00" and line(data, "Rent")["overdue"] is False


def test_a_by_date_target_that_fell_behind_is_overdue(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    target(client, rent, "by_date", "500", target_date=THIS_MONTH.isoformat())
    assert line(budget(client), "Rent")["overdue"] is False
    later = budget(client, add_months(THIS_MONTH, 1))
    assert line(later, "Rent")["overdue"] is True and line(later, "Rent")["underfunded"] == "500.00"
    assign(client, rent, "500")
    assert line(budget(client, add_months(THIS_MONTH, 1)), "Rent")["overdue"] is False


def test_validation(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    url = f"/api/budget/categories/{rent['aid']}/target"
    assert client.put(url, json={"kind": "weekly", "amount": "5"}).status_code == 400  # which day?
    assert client.put(url, json={"kind": "weekly", "amount": "5", "weekday": 7}).status_code == 422
    assert client.put(url, json={"kind": "yearly", "amount": "5"}).status_code == 400  # which month?
    ok = client.put(url, json={"kind": "monthly", "amount": "5", "weekday": 2})  # stray fields are dropped
    assert ok.status_code == 200 and line(ok.json(), "Rent")["target"]["weekday"] is None


# ---- the page, the backup and the assistants -----------------------------------------------------------------------


@pytest.fixture
def setup(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    return {"bank": bank, "food": food, "rent": rent}


def test_the_form_and_the_page(client, setup):
    rent = setup["rent"]["aid"]
    form = client.get(f"/budget/target?category={rent}").text
    assert 'value="weekly"' in form and 'value="yearly"' in form and "data-target-weekday" in form
    saved = client.post("/budget/target", data={"category": rent, "kind": "weekly", "amount": "100", "weekday": "4"})
    assert saved.status_code == 200 and "budget-target" in saved.headers["set-cookie"]
    page = client.get(f"/budget/category/{rent}/sheet").text
    assert "Weekly 100.00 on Fris" in page.replace("\n", " ").replace("  ", " ")
    assert 'value="4" selected' in client.get(f"/budget/target?category={rent}").text

    due = add_months(THIS_MONTH, 2)
    saved = client.post("/budget/target", data={"category": rent, "kind": "yearly", "amount": "600", "target_date": due.strftime("%Y-%m")})
    assert saved.status_code == 200
    assert f"Yearly 600.00 in {due:%b}" in client.get(f"/budget/category/{rent}/sheet").text.replace("\n", " ").replace("  ", " ")


def test_form_errors(client, setup):
    rent = setup["rent"]["aid"]
    for data in (
        {"kind": "weekly", "amount": "100"},
        {"kind": "weekly", "amount": "100", "weekday": "9"},
        {"kind": "yearly", "amount": "100"},
    ):
        bad = client.post("/budget/target", data={"category": rent, **data})
        assert bad.status_code == 400 and bad.headers["HX-Retarget"] == "#form-error", data


def test_overdue_is_shown_on_the_page(client, setup):
    from .test_web_goal import goal, months_ahead

    assert goal(client, amount="500", by=months_ahead(1), assign_now=None).status_code == 200
    later = add_months(THIS_MONTH, 2)
    assert "Past its month · 500.00 short" in client.get(f"/budget?tab=save&month={later:%Y-%m}").text.replace("\n", " ").replace("  ", " ")
