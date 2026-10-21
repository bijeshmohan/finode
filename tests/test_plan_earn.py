"""The Plan's Earn section: the income expected each month (docs/developer/plan-design.md).

Expected amounts are plan rows for Income accounts; what came in is read from the ledger. Earn is informational: it never
changes Ready to assign, and nothing carries over from one month to the next.
"""

from datetime import date, timedelta

import pytest

from .test_budget import account, assign, budget, identity, move

THIS = date.today().replace(day=1)
LAST = (THIS - timedelta(days=1)).replace(day=1)


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="10000")
    salary = account(client, root_accounts, "Salary", "Income")
    interest = account(client, root_accounts, "Interest", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    return {"bank": bank, "salary": salary, "interest": interest, "food": food, "roots": root_accounts}


def earn(data, name):
    return next(l for l in data["earning"] if l["name"] == name)


def pay(client, books, amount, on=None, account="salary"):
    move(client, books[account], books["bank"], amount, on=on)  # income: credit Salary, debit Bank


def test_every_open_income_account_is_a_line_with_nothing_expected(client, books):
    data = budget(client)
    assert [l["name"] for l in data["earning"]] == ["Interest", "Salary"] and data["earning_expected"] == "0.00"
    assert earn(data, "Salary")["expected"] == "0.00" and earn(data, "Salary")["received"] == "0.00"


def test_expecting_income_changes_nothing_about_ready_to_assign(client, books):
    before = budget(client)["ready_to_assign"]
    data = assign(client, books["salary"], "85000")
    assert earn(data, "Salary")["expected"] == "85000.00" and data["earning_expected"] == "85000.00"
    assert data["ready_to_assign"] == before == "10000.00", "only money that has arrived counts"
    identity(data)


def test_what_came_in_is_read_from_the_ledger_for_the_month(client, books):
    assign(client, books["salary"], "85000")
    pay(client, books, "85000")
    pay(client, books, "2000", on=LAST.isoformat(), account="interest")  # last month's, not this one's
    data = budget(client)
    assert earn(data, "Salary")["received"] == "85000.00" and earn(data, "Interest")["received"] == "0.00"
    assert data["earning_received"] == "85000.00" and data["ready_to_assign"] == "97000.00", "it arrived: now it can be assigned"
    assert earn(budget(client, LAST), "Interest")["received"] == "2000.00"
    identity(data)


def test_nothing_carries_over_and_each_month_is_its_own(client, books):
    assign(client, books["salary"], "5000", month=LAST)
    assert earn(budget(client), "Salary")["expected"] == "0.00"
    assert earn(budget(client, LAST), "Salary")["expected"] == "5000.00"


def test_the_plan_for_income_never_starts_the_budget_or_counts_as_assigned_ahead(client, books):
    later = (THIS + timedelta(days=40)).replace(day=1)
    assign(client, books["salary"], "9000", month=later)
    data = budget(client)
    assert data["assigned_to_later_months"] == "0.00" and data["assigned"] == "0.00" and data["ready_to_assign"] == "10000.00"
    assert data["copyable"] == "0.00"
    old = assign(client, books["salary"], "1000", month=date(2025, 1, 1))
    assert old["activity"] == "0.00"
    spent = account(client, books["roots"], "Eat", "Expenses")
    move(client, books["bank"], spent, "300", on=(THIS - timedelta(days=500)).isoformat())
    assert budget(client)["overspent_last_month"] == "0.00", "expected income dated early does not move where budgeting starts"


def test_income_cannot_be_negative_moved_or_given_a_target(client, books):
    assert client.put(f"/api/budget/categories/{books['salary']['aid']}", json={"amount": "-5"}).status_code == 400
    assign(client, books["food"], "100")
    refused = client.post("/plan/move", data={"from_category": books["food"]["aid"], "to_category": books["salary"]["aid"], "amount": "10"})
    assert refused.status_code == 400 and "cannot be moved" in refused.text
    target = client.put(f"/api/budget/categories/{books['salary']['aid']}/target", json={"kind": "monthly", "amount": "10"})
    assert target.status_code == 400


def test_a_group_is_a_line_only_while_something_is_planned_or_received(client, books):
    freelance = account(client, books["roots"], "Freelance", "Income")
    client.post("/api/accounts/", json={"name": "Client A", "parent_id": freelance["aid"]})
    names = [l["name"] for l in budget(client)["earning"]]
    assert "Client A" in names and "Freelance (other)" not in names and "Freelance" not in names
    data = assign(client, freelance, "700")
    assert earn(data, "Freelance (other)")["expected"] == "700.00" and earn(data, "Freelance (other)")["path"] == "Freelance (other)"
    assert earn(data, "Client A")["path"] == "Freelance:Client A"


def test_copy_last_month_copies_expected_income_too(client, books):
    assign(client, books["salary"], "80000", month=LAST)
    copied = client.post("/plan/copy", data={"month": THIS.isoformat()[:7]})
    assert copied.status_code == 200, copied.text
    assert earn(budget(client), "Salary")["expected"] == "80000.00"


def test_a_deleted_income_account_takes_its_plan_with_it_and_restores_it(client, books, svc):
    assign(client, books["interest"], "300")
    assert client.delete(f"/api/accounts/{books['interest']['aid']}").status_code == 204
    assert "Interest" not in [l["name"] for l in budget(client)["earning"]]
    [gone] = svc.accounts.restorable()
    assert client.post(f"/accounts/deleted/{gone['did']}/restore").status_code == 200
    assert earn(budget(client), "Interest")["expected"] == "300.00"


def test_the_period_lock_closes_the_plan_for_income_as_for_everything_else(client, books):
    client.patch("/api/profile/", json={"locked_through": (THIS - timedelta(days=1)).isoformat()})
    refused = client.put(f"/api/budget/categories/{books['salary']['aid']}", json={"month": LAST.isoformat(), "amount": "10"})
    assert refused.status_code == 400 and "locked" in refused.text
