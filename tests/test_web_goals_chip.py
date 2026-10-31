"""The Goals chip: goals leave Left to spend and the budget list, show on their own chip, and have a sheet, an edit form, a way to hand their money to a category and a delete."""

import re
from datetime import date, timedelta
from decimal import Decimal
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
    assert after["available"] == before["available"] and after["assigned"] == before["assigned"], (
        "Left to spend does not include the goal"
    )
    assert after["goal_available"] == "16666.67"
    assert float(after["ready_to_assign"]) == pytest.approx(float(before["ready_to_assign"]) - 16666.67), (
        "the money has a job"
    )
    identity(after)
    assert "Goa trip" not in {l["name"] for l in after["lines"]}
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": books["food"]["aid"], "side": "debit", "amount": "100"},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "100"},
            ]
        },
    )
    home = client.get("/").text
    assert "Left to spend" in home and "2,900" in home and "19,566" not in home, (
        "Home's Left to spend leaves the goal out too"
    )


def test_the_goals_chip_lists_goals_and_budgets_does_not(client, books):
    goal(client)
    goals = client.get(f"/budget?tab=save&month={MONTH}").text
    assert "Saved for goals" in goals and "16,666.67" in goals and "Goa trip" in goals and "This month done" in goals
    assert "of 1,00,000.00" in goals and "by " + date.fromisoformat(months_ahead(5) + "-01").strftime("%b %Y") in goals
    assert "Left to spend" not in goals and "data-budget-tree" not in goals
    budgets = client.get(f"/budget?month={MONTH}").text
    assert "Goa trip" not in budgets.split("data-budget-tree", 1)[1], "not in the list of budgets"
    assert "in goals" in budgets and "tab=save" in budgets, "a quiet line says how much and links to Goals"


def test_the_ready_to_assign_sum_adds_up_with_goals(client, books):
    goal(client)
    page = client.get(f"/budget?month={MONTH}").text
    sums = re.findall(r'<p class="calc-row-line([^"]*)"><span>([^<]*)</span><b>([^<]*)</b>', page)
    labels = {label: amount for _, label, amount in sums}
    assert labels["Set aside for goals"] == "₹16,666.67"


def test_an_empty_goals_chip_offers_the_first_step(client, books):
    text = client.get("/budget?tab=save").text
    assert "No goals yet" in text and 'href="/budget/goal"' in text


def test_a_goal_that_still_needs_this_months_share_says_so_and_the_sheet_sets_it_aside(client, books):
    goal(client, assign_now=None)
    text = client.get(f"/budget?tab=save&month={MONTH}").text
    assert "16,666.67 to go this month" in text
    g = the_goal(client)
    sheet = client.get(f"/budget/goal/{g['gid']}/sheet?month={MONTH}").text
    assert "Goa trip" in sheet and "Set aside 16,666.67 this month" in sheet and "Delete goal" in sheet
    assert "Record spending" not in sheet and "/transactions/new" not in sheet, "spending is recorded on a category"
    assert "Use it for" not in sheet, "nothing saved yet, nothing to hand over"
    done = client.post(f"/budget/goal/{g['gid']}/assign", data={"month": MONTH, "amount": "16,666.67"})
    assert done.status_code == 200 and "data-budget-goals" in done.text and "This month done" in done.text
    after = client.get(f"/budget/goal/{g['gid']}/sheet?month={MONTH}").text
    assert "this month</button>" not in after, "nothing left to set aside"
    assert "Use it for" in after
    assert the_goal(client)["assigned"] == "16666.67"


def test_a_goal_hands_its_money_to_the_category_that_paid(client, books):
    goal(client)
    hospital = account(client, books["roots"], "Hospital", "Expenses")
    # the hospital bill is recorded on its category as always, and overspends it
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": hospital["aid"], "side": "debit", "amount": "6000"},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "6000"},
            ]
        },
    )
    before = api(client)
    g = the_goal(client)
    page = client.get(f"/budget/goal/{g['gid']}/use?month={MONTH}").text
    assert (
        "Use Goa trip for" in page
        and "Hospital · 6,000.00 over" in unescape(page)
        and 'value="6,000.00"' in page.replace("₹", "")
    )
    assert f'<option value="{hospital["aid"]}" selected' in page, "the category that is over comes first"
    done = client.post(
        f"/budget/goal/{g['gid']}/use", data={"category": hospital["aid"], "amount": "6000", "month": MONTH}
    )
    assert done.status_code == 200, done.text
    after = api(client)
    assert the_goal(client)["available"] == "10666.67" and the_goal(client)["assigned"] == "10666.67"
    line = next(l for l in after["lines"] if l["name"] == "Hospital")
    assert line["assigned"] == "6000.00" and line["available"] == "0.00", "covered"
    assert after["ready_to_assign"] == before["ready_to_assign"], "money only moved from a goal to a category"
    identity(after)


@pytest.mark.parametrize(
    ("amount", "message"), [("0", "positive"), ("99999", "nly 16666.67 is saved"), ("1.005", "decimal")]
)
def test_a_goal_cannot_hand_over_what_it_does_not_have(client, books, amount, message):
    goal(client)
    g = the_goal(client)
    refused = client.post(
        f"/budget/goal/{g['gid']}/use", data={"category": books["food"]["aid"], "amount": amount, "month": MONTH}
    )
    assert refused.status_code == 400 and message in refused.text
    assert the_goal(client)["available"] == "16666.67"


def test_a_goal_can_be_changed(client, books):
    goal(client)
    g = the_goal(client)
    page = client.get(f"/budget/goal/{g['gid']}/edit").text
    assert 'value="Goa trip"' in page and f'value="{months_ahead(5)}"' in page
    assert "assign_now" not in page, "only a new goal sets money aside"
    done = client.post(
        f"/budget/goal/{g['gid']}", data={"name": "Goa and Hampi", "amount": "150000", "by": months_ahead(8)}
    )
    assert done.status_code == 200, done.text
    changed = the_goal(client, "Goa and Hampi")
    assert changed["amount"] == "150000.00" and changed["target_date"] == f"{months_ahead(8)}-01"
    assert changed["available"] == "16666.67", "what was saved stays"
    assert (
        client.post(
            f"/budget/goal/{g['gid']}", data={"name": "Goa and Hampi", "amount": "1", "by": months_ahead(0)}
        ).status_code
        == 400
    )


def test_deleting_a_goal_gives_its_money_back_to_ready_to_assign(client, books):
    before = api(client)["ready_to_assign"]
    goal(client)
    assert api(client)["ready_to_assign"] != before
    g = the_goal(client)
    assert client.post(f"/budget/goal/{g['gid']}/delete").status_code == 200
    assert api(client)["goals"] == [] and api(client)["ready_to_assign"] == before


def test_the_goal_pages_refuse_what_is_not_a_goal(client, books):
    food = books["food"]["aid"]
    for path in (f"/budget/goal/{food}/sheet", f"/budget/goal/{food}/edit", f"/budget/goal/{food}/use"):
        assert client.get(path).status_code == 404
    assert (
        client.post(f"/budget/goal/{food}", data={"name": "x", "amount": "1", "by": months_ahead(2)}).status_code == 400
    )
    assert client.post(f"/budget/goal/{food}/delete").status_code == 400
    assert client.post(f"/budget/goal/{food}/assign", data={"amount": "5"}).status_code == 400
    assert "Food" in {c["name"] for c in client.get("/api/categories/").json()}


def test_copying_last_months_amounts_includes_goals(session, books, client):
    from .svc import services

    budget = services(session).budget
    budget.create_goal("Bike", Decimal("12000"), THIS_MONTH.replace(year=THIS_MONTH.year + 1), False)
    last = (THIS_MONTH - timedelta(days=1)).replace(day=1)
    budget.assign_goal(last, budget.view(THIS_MONTH).goals[0].gid, Decimal("500"))
    assert budget.view(THIS_MONTH).copyable == Decimal("500")
    budget.copy_previous(THIS_MONTH)
    assert budget.view(THIS_MONTH).goals[0].assigned == 500


def test_the_assistants_see_goals_apart(client, books, session):
    goal(client)
    from .svc import services

    data = services(session).budget.view(THIS_MONTH)
    assert [g.name for g in data.goals] == ["Goa trip"] and data.goal_available == data.goals[0].available
