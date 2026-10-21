"""Gentler first steps: new profiles start with Spend only, a welcome on the Plan, folded budget options."""

import pytest

from app.repositories import profile

from .test_budget import account


@pytest.fixture
def new_person(monkeypatch):
    """A person with a brand-new profile: Advanced off, and the Plan with Spend only."""
    monkeypatch.setattr(profile, "NEW_PROFILE_ADVANCED", False)
    monkeypatch.setattr(profile, "NEW_PROFILE_PLAN_BUILD", False)
    monkeypatch.setattr(profile, "NEW_PROFILE_PLAN_EARN", False)


def test_a_new_profile_starts_with_only_spend_and_can_add_build(client, root_accounts, new_person):
    text = client.get("/plan").text
    assert ">Build<" not in text and ">Earn<" not in text and "/plan/configure" in text
    assert client.post("/plan/configure", data={"month": "2026-10", "tab": "spend", "build": "1"}).status_code == 200
    assert ">Build<" in client.get("/plan").text


def test_build_stays_for_people_who_already_had_it(client, root_accounts, new_person):
    client.patch("/api/profile/", json={"plan_build": True})
    assert ">Build<" in client.get("/plan").text


def test_the_plan_welcomes_a_new_person_until_something_is_assigned(client, root_accounts, new_person):
    assert "Give every" in client.get("/plan").text
    assert "Start with your first category" in client.get("/plan").text
    account(client, root_accounts, "Bank", "Assets", balance="1000")
    food = account(client, root_accounts, "Food", "Expenses")
    text = client.get("/plan").text
    assert "Give every" in text and "Tap a category below" in text and "Start with your first category" not in text
    client.put(f"/api/budget/categories/{food['aid']}", json={"amount": "300"})
    assert "Give every" not in client.get("/plan").text


def test_people_on_advanced_do_not_get_the_welcome(client, root_accounts):
    assert "Give every" not in client.get("/plan").text


def test_the_account_form_folds_the_budget_choices_and_says_where_it_stands(client, root_accounts, new_person):
    text = client.get(f"/accounts/new?parent={root_accounts['Assets']}").text
    assert "Budget options" in text and "Part of the budget" in text and "data-budget-summary" in text
    assert 'name="saving"' not in text, "Build is off, so the row is not offered"
    client.patch("/api/profile/", json={"plan_build": True})
    assert 'name="saving"' in client.get(f"/accounts/new?parent={root_accounts['Assets']}").text


def test_an_account_already_in_build_keeps_its_row_even_when_the_section_is_off(client, root_accounts, new_person):
    fund = account(client, root_accounts, "Mutual Funds", "Assets", on_budget=False, saving=True)
    text = client.get(f"/accounts/{fund['aid']}/edit").text
    assert 'name="saving" value="1" checked' in text and "Planned under Build" in text
