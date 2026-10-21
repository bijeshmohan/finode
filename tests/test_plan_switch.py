"""FINODE_PLAN_ENABLED=false puts the app back to the budget-only behaviour without touching anything stored."""

from decimal import Decimal

import pytest

from app.config import settings

from .test_budget import account, assign, budget, identity, move
from .test_plan_earn import earn  # noqa: F401
from .test_plan_save import saving  # noqa: F401


@pytest.fixture
def planned(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="10000")
    fund = account(client, root_accounts, "Fund", "Assets", on_budget=False, saving=True)
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    assign(client, food, "1000")
    assign(client, fund, "2000")
    assign(client, salary, "5000")
    move(client, bank, fund, "500")
    return {"bank": bank, "fund": fund, "salary": salary, "food": food, "roots": root_accounts}


def test_with_the_plan_on_save_and_earn_count(client, planned):
    data = budget(client)
    assert data["saving_assigned"] == "2000.00" and data["earning_expected"] == "5000.00"
    identity(data)


def test_switched_off_the_budget_reads_as_it_did_before_save_and_earn(client, planned, monkeypatch):
    on = budget(client)
    monkeypatch.setattr(settings, "plan_enabled", False)
    off = budget(client)
    assert off["saving"] == [] and off["earning"] == [] and off["saving_available"] == "0.00" and off["earning_expected"] == "0.00"
    # What the budget-only app says: cash minus the categories' available money, with the Save plan not in it.
    assert Decimal(off["ready_to_assign"]) == Decimal(on["ready_to_assign"]) + Decimal(on["saving_available"])
    identity(off)
    assert [l["name"] for l in off["lines"]] == [l["name"] for l in on["lines"]], "Spend is untouched"
    assert off["available"] == on["available"] and off["assigned"] == on["assigned"]


def test_switched_off_nothing_can_be_planned_for_saving_or_expected(client, planned, monkeypatch):
    monkeypatch.setattr(settings, "plan_enabled", False)
    assert client.put(f"/api/budget/categories/{planned['fund']['aid']}", json={"amount": "5"}).status_code == 400
    assert client.put(f"/api/budget/categories/{planned['salary']['aid']}", json={"amount": "5"}).status_code == 400
    other = account(client, planned["roots"], "Other", "Assets", on_budget=False)
    refused = client.patch(f"/api/accounts/{other['aid']}", json={"saving": True})
    assert refused.status_code == 400 and "switched off" in refused.text


def test_switched_off_the_page_has_no_chips_and_the_forms_no_saving_switch(client, planned, monkeypatch):
    monkeypatch.setattr(settings, "plan_enabled", False)
    text = client.get("/plan?tab=save").text
    assert "cat-chips" not in text and "data-budget-saving" not in text and "data-budget-tree" in text
    assert "Plan for saving" not in client.get(f"/accounts/{planned['fund']['aid']}/edit").text
    assert "Plan for saving" not in client.get("/accounts/new?root=assets").text


def test_switching_it_back_on_brings_everything_back(client, planned, monkeypatch):
    before = budget(client)
    monkeypatch.setattr(settings, "plan_enabled", False)
    budget(client)
    monkeypatch.setattr(settings, "plan_enabled", True)
    after = budget(client)
    assert after["saving"] == before["saving"] and after["earning"] == before["earning"]
    assert after["ready_to_assign"] == before["ready_to_assign"]
