"""A goal is an Expenses category with a by-date target, made in one step from Plans."""

from datetime import date
from html import unescape

import pytest

from .test_budget import account

THIS_MONTH = date.today().replace(day=1)


def months_ahead(n: int) -> str:
    index = THIS_MONTH.year * 12 + THIS_MONTH.month - 1 + n
    return f"{index // 12}-{index % 12 + 1:02d}"


@pytest.fixture
def books(client, root_accounts):
    account(client, root_accounts, "Bank", "Assets", balance="500000")
    return root_accounts


def goal(client, **form):
    data = {"name": "Goa trip", "amount": "100000", "by": months_ahead(5), "assign_now": "1", **form}
    return client.post("/plan/goal", data={k: v for k, v in data.items() if v is not None})


def category(client, name):
    return next((a for a in client.get("/api/accounts/").json() if a["name"] == name), None)


def test_the_goals_chip_links_to_the_form_and_the_form_asks_three_things(client, books):
    assert 'href="/plan/goal"' in client.get("/plan?tab=goals").text
    assert 'href="/plan/goal"' not in client.get("/plan").text, "the Budgets chip is about spending"
    page = client.get("/plan/goal").text
    assert "New goal" in page and 'name="name"' in page and 'name="amount"' in page and 'name="by"' in page
    assert f'min="{months_ahead(1)}"' in page, "a month after this one"
    assert 'name="assign_now" value="1" checked' in page, "this month's share is set aside unless unticked"


def test_creating_a_goal_makes_the_category_the_target_and_this_months_share(client, books):
    done = goal(client)
    assert done.status_code == 200, done.text
    made = category(client, "Goa trip")
    roots = {a["aid"]: a["name"] for a in client.get("/api/accounts/").json() if a["parent_id"] is None}
    assert roots[made["parent_id"]] == "Expenses"
    data = client.get("/api/budget/").json()
    line = next(l for l in data["goals"] if l["name"] == "Goa trip")
    assert line["target"]["kind"] == "by_date" and line["target"]["amount"] == "100000.00"
    assert line["target"]["target_date"] == f"{months_ahead(5)}-01"
    assert line["assigned"] == "16666.67", "100000 over this month and the 5 after it, rounded up"
    assert line["underfunded"] == "0.00"


def test_unticking_the_share_leaves_nothing_assigned(client, books):
    assert goal(client, assign_now=None).status_code == 200
    line = next(l for l in client.get("/api/budget/").json()["goals"] if l["name"] == "Goa trip")
    assert line["assigned"] == "0.00" and line["underfunded"] == "16666.67" and line["target"]["kind"] == "by_date"


def test_the_preview_says_what_a_month_takes(client, books):
    page = client.get("/plan/goal/preview", params={"amount": "100000", "by": months_ahead(5)}).text
    assert "16,666.67 a month" in page.replace("₹", "") and "for 6 months" in page
    assert "—" in client.get("/plan/goal/preview").text, "nothing to work out yet"
    assert "after this one" in client.get("/plan/goal/preview", params={"amount": "100", "by": months_ahead(0)}).text


@pytest.mark.parametrize("form,message", [
    ({"name": ""}, "what the goal is for"),
    ({"amount": ""}, "how much you need"),
    ({"amount": "0"}, "must be positive"),
    ({"amount": "abc"}, "amount"),
    ({"by": ""}, "month you need it by"),
    ({"by": months_ahead(0)}, "after this one"),
    ({"by": months_ahead(-3)}, "after this one"),
    ({"amount": "10.005"}, "decimal"),
])
def test_a_goal_that_cannot_work_is_refused_and_saves_nothing(client, books, form, message):
    before = len(client.get("/api/accounts/").json())
    refused = goal(client, **form)
    assert refused.status_code == 400 and message in refused.text.lower()
    assert len(client.get("/api/accounts/").json()) == before, "no category is left behind"


def test_a_name_that_is_taken_is_refused(client, books):
    account(client, books, "Travel", "Expenses")
    refused = goal(client, name="travel")
    assert refused.status_code == 400 and "already has an account called 'Travel'" in unescape(refused.text)
    assert goal(client).status_code == 200
    assert goal(client).status_code == 400, "the same goal twice"
