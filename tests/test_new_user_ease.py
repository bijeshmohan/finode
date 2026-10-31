"""Gentler first steps: a welcome on the Plan until something is assigned, folded budget options."""

import pytest

from .test_budget import account


@pytest.fixture
def new_person():
    """A person with a brand-new profile (every profile is the same now; the fixture is kept for the reading of the tests)."""


def test_the_plan_welcomes_a_new_person_until_something_is_assigned(client, root_accounts, new_person):
    assert "Give every" in client.get("/budget").text
    assert "Start with your first category" in client.get("/budget").text
    account(client, root_accounts, "Bank", "Assets", balance="1000")
    food = account(client, root_accounts, "Food", "Expenses")
    text = client.get("/budget").text
    assert "Give every" in text and "Tap a category below" in text and "Start with your first category" not in text
    client.put(f"/api/budget/categories/{food['id']}", json={"amount": "300"})
    assert "Give every" not in client.get("/budget").text


def test_the_account_form_folds_the_budget_choices_and_says_where_it_stands(client, root_accounts, new_person):
    text = client.get(f"/accounts/new?parent={root_accounts['Assets']}").text
    assert "Budget options" in text and "Part of the budget" in text and "data-budget-summary" in text
