"""The head of Budgets: Ready to assign as the one figure, with a quiet note under it (Left to spend lives on Home)."""

import re
from datetime import date

import pytest

from .test_budget import account, assign, move

MONTH = date.today().strftime("%Y-%m")


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    food = account(client, root_accounts, "Food", "Expenses")
    return {"bank": bank, "food": food}


def head(client):
    page = client.get(f"/budget?month={MONTH}").text
    start = page.index("data-budget-head")
    return page[start : start + 3000], page


def test_the_head_is_ready_to_assign_and_left_to_spend_is_not_on_the_page(client, books):
    assign(client, books["food"], "5000")
    move(client, books["bank"], books["food"], "1200")
    text, page = head(client)
    assert "Ready to assign" in text and "95,000.00" in text, "100,000 in the account less 5,000 in a category"
    assert "Give it a job: tap a category" in text
    assert "Left to spend" not in page.split("<h2")[0] and "glance-bar" not in text, "Home has the figure and the bar"
    assert "Spent" not in text and "ready-warn assigned" not in page


def test_the_head_says_what_it_is_made_of_in_the_i(client, books):
    _, page = head(client)
    for label in (
        "In your accounts",
        "Set aside for card bills",
        "Left in your categories",
        "Assigned to later months",
    ):
        assert label in page


def test_the_head_at_zero_says_every_rupee_has_a_job(client, books):
    assign(client, books["food"], "100000")
    text, _ = head(client)
    assert "has a job" in text and "Give it a job" not in text


def test_the_head_says_when_over_assigned_and_the_figure_stays_at_zero(client, books):
    assign(client, books["food"], "150000")
    text, page = head(client)
    assert 'class="hero-warn"' in text and "Over-assigned by" in text and "50,000.00" in text
    assert re.search(r'<span class="figure">[^\n]*</span>0\.00</span>', text), "the figure never goes below zero"
    assert "ready-warn assigned" not in page


def test_with_nothing_to_assign_and_nothing_planned_the_head_says_so(client, root_accounts):
    page = client.get(f"/budget?month={MONTH}").text
    assert "Nothing to assign yet" in page


def test_the_page_has_two_chips_spend_and_save_and_spend_is_chosen(client, books):
    page = client.get(f"/budget?month={MONTH}").text
    assert 'aria-label="What to plan"' in page
    assert re.search(r'aria-pressed="true">Spend</a>', page) and re.search(r'aria-pressed="false">Save</a>', page)
    assert "/budget/configure" not in page
    assert client.get("/budget/configure").status_code == 404
