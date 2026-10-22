"""The Goals chip: goals leave Left to spend and the budget list, show on their own chip, and have a sheet, an edit form and a delete."""

import re
from datetime import date
from html import unescape

import pytest

from .test_budget import account, identity
from .test_web_goal import goal, months_ahead

THIS_MONTH = date.today().replace(day=1)
MONTH = THIS_MONTH.strftime("%Y-%m")


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="500000")
    food = account(client, root_accounts, "Food", "Expenses")
    client.put(f"/api/budget/categories/{food['aid']}", json={"amount": "3000"})
    return {"bank": bank, "food": food, "roots": root_accounts}


def api(client):
    return client.get("/api/budget/").json()


def the_goal(client, name="Goa trip"):
    return next(g for g in api(client)["goals"] if g["name"] == name)


def test_a_goal_is_not_money_to_spend_but_still_has_a_job(client, books):
    before = api(client)
    assert goal(client).status_code == 200
    after = api(client)
    assert after["available"] == before["available"] and after["assigned"] == before["assigned"], "Left to spend does not include the goal"
    assert after["goal_available"] == "16666.67"
    assert float(after["ready_to_assign"]) == pytest.approx(float(before["ready_to_assign"]) - 16666.67), "the money has a job"
    identity(after)
    assert "Goa trip" not in {l["name"] for l in after["lines"]}
    client.post("/api/transactions/", json={"postings": [
        {"account": books["food"]["aid"], "side": "debit", "amount": "100"}, {"account": books["bank"]["aid"], "side": "credit", "amount": "100"}]})
    home = client.get("/").text
    assert "Left to spend" in home and "2,900" in home and "19,566" not in home, "Home's Left to spend leaves the goal out too"


def test_a_goal_can_be_told_apart_from_other_targets(client, books):
    other = account(client, books["roots"], "Rent", "Expenses")
    client.put(f"/api/budget/categories/{other['aid']}/target", json={"kind": "monthly", "amount": "500"})
    yearly = account(client, books["roots"], "Insurance", "Expenses")
    client.put(f"/api/budget/categories/{yearly['aid']}/target", json={"kind": "yearly", "amount": "12000", "target_date": f"{months_ahead(6)}-01"})
    data = api(client)
    assert {l["name"] for l in data["lines"]} >= {"Rent", "Insurance"} and data["goals"] == []
    # a by-date target on a category that already exists makes it a goal, and removing it brings it back
    client.put(f"/api/budget/categories/{other['aid']}/target", json={"kind": "by_date", "amount": "9000", "target_date": f"{months_ahead(3)}-01"})
    data = api(client)
    assert [g["name"] for g in data["goals"]] == ["Rent"] and "Rent" not in {l["name"] for l in data["lines"]}
    client.delete(f"/api/budget/categories/{other['aid']}/target")
    assert api(client)["goals"] == []


def test_the_goals_chip_lists_goals_and_budgets_does_not(client, books):
    goal(client)
    goals = client.get(f"/plan?tab=goals&month={MONTH}").text
    assert "Saved for goals" in goals and "16,666.67" in goals and "Goa trip" in goals and "This month done" in goals
    assert "of 1,00,000.00" in goals and "by " + date.fromisoformat(months_ahead(5) + "-01").strftime("%b %Y") in goals
    assert "Left to spend" not in goals and 'data-budget-tree' not in goals
    budgets = client.get(f"/plan?month={MONTH}").text
    assert "Goa trip" not in budgets.split("data-budget-tree", 1)[1], "not in the list of budgets"
    assert "in goals" in budgets and "tab=goals" in budgets, "a quiet line says how much and links to Goals"


def test_the_ready_to_assign_sum_adds_up_with_goals(client, books):
    goal(client)
    page = client.get(f"/plan?month={MONTH}").text
    sums = re.findall(r'<p class="calc-row-line([^"]*)"><span>([^<]*)</span><b>([^<]*)</b>', page)
    labels = {label: amount for _, label, amount in sums}
    assert labels["Set aside for goals"] == "₹16,666.67"


def test_an_empty_goals_chip_offers_the_first_step(client, books):
    text = client.get("/plan?tab=goals").text
    assert "No goals yet" in text and 'href="/plan/goal"' in text


def test_a_goal_that_still_needs_this_months_share_says_so_and_the_sheet_sets_it_aside(client, books):
    goal(client, assign_now=None)
    text = client.get(f"/plan?tab=goals&month={MONTH}").text
    assert "16,666.67 to go this month" in text
    g = the_goal(client)
    sheet = client.get(f"/plan/goal/{g['aid']}/sheet?month={MONTH}").text
    assert "Goa trip" in sheet and "Set aside 16,666.67 this month" in sheet and "Record spending on it" in sheet and "Delete goal" in sheet
    assert f"/transactions/new?account={g['aid']}" in sheet
    done = client.post("/plan/assign", data={"category": g["aid"], "month": MONTH, "amount": "16,666.67", "tab": "goals", "sheet": "1"})
    assert done.status_code == 200 and "data-budget-goals" in done.text and "This month done" in done.text
    assert "this month</button>" not in client.get(f"/plan/goal/{g['aid']}/sheet?month={MONTH}").text, "nothing left to set aside"
    assert the_goal(client)["assigned"] == "16666.67"


def test_spending_on_a_goal_lowers_what_is_saved(client, books):
    goal(client)
    g = the_goal(client)
    client.post("/api/transactions/", json={"postings": [
        {"account": g["aid"], "side": "debit", "amount": "6000"}, {"account": books["bank"]["aid"], "side": "credit", "amount": "6000"}]})
    after = the_goal(client)
    assert after["available"] == "10666.67" and after["activity"] == "6000.00"
    identity(api(client))


def test_a_goal_can_be_changed(client, books):
    goal(client)
    g = the_goal(client)
    page = client.get(f"/plan/goal/{g['aid']}/edit").text
    assert 'value="Goa trip"' in page and 'value="100,000.00"' in unescape(page).replace("1,00,000.00", "100,000.00") and f'value="{months_ahead(5)}"' in page
    assert "assign_now" not in page, "only a new goal sets money aside"
    done = client.post(f"/plan/goal/{g['aid']}", data={"name": "Goa and Hampi", "amount": "150000", "by": months_ahead(8)})
    assert done.status_code == 200, done.text
    changed = the_goal(client, "Goa and Hampi")
    assert changed["target"]["amount"] == "150000.00" and changed["target"]["target_date"] == f"{months_ahead(8)}-01"
    assert changed["available"] == "16666.67", "what was saved stays"
    assert client.post(f"/plan/goal/{g['aid']}", data={"name": "Goa and Hampi", "amount": "1", "by": months_ahead(0)}).status_code == 400


def test_a_goal_is_deleted_or_closed_when_it_has_spending(client, books):
    goal(client)
    g = the_goal(client)
    assert client.post(f"/plan/goal/{g['aid']}/delete").status_code == 200
    assert api(client)["goals"] == [] and not any(a["name"] == "Goa trip" for a in client.get("/api/accounts/").json())
    goal(client, name="Bike")
    bike = the_goal(client, "Bike")
    client.post("/api/transactions/", json={"postings": [
        {"account": bike["aid"], "side": "debit", "amount": "100"}, {"account": books["bank"]["aid"], "side": "credit", "amount": "100"}]})
    assert client.post(f"/plan/goal/{bike['aid']}/delete").status_code == 200
    closed = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Bike")
    assert closed["closed_on"], "with spending it is closed, and its history stays"


def test_the_goal_pages_refuse_what_is_not_a_goal(client, books):
    food = books["food"]["aid"]
    for path in (f"/plan/goal/{food}/sheet", f"/plan/goal/{food}/edit"):
        assert client.get(path).status_code == 404
    assert client.post(f"/plan/goal/{food}", data={"name": "x", "amount": "1", "by": months_ahead(2)}).status_code == 400
    assert client.post(f"/plan/goal/{food}/delete").status_code == 400
    assert "Food" in {a["name"] for a in client.get("/api/accounts/").json()}


def test_assign_what_is_needed_also_funds_goals(client, books):
    goal(client, assign_now=None)
    funded = client.post("/plan/fund", data={"month": MONTH, "tab": "goals"})
    assert funded.status_code == 200 and "This month done" in funded.text
    assert the_goal(client)["assigned"] == "16666.67"


def test_the_assistants_see_goals_apart(client, books, session):
    goal(client)
    from .svc import services

    data = services(session).budget.view(THIS_MONTH)
    assert [g.name for g in data.goals] == ["Goa trip"] and data.goal_available == data.goals[0].available
