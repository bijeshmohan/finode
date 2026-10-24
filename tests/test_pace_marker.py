"""The tick that shows how far through the month today is, on the bars of the current month."""

from datetime import date

import pytest

from app import clock
from app.clock import month_progress

from .test_budget import account, assign, move


def test_month_progress_is_the_share_of_the_month_that_has_passed():
    assert month_progress(date(2026, 4, 15)) == 50  # 15 of 30
    assert month_progress(date(2026, 4, 30)) == 100
    assert month_progress(date(2026, 2, 14)) == 50  # 14 of 28
    assert month_progress(date(2026, 1, 1)) == 3


@pytest.fixture
def setup(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="1000")
    food = account(client, root_accounts, "Food", "Expenses")
    assign(client, food, "300")
    return {"bank": bank, "food": food}


def test_the_budget_rows_carry_no_tick_it_is_on_home_and_in_a_groups_head(client, setup):
    assert 'class="pace"' not in client.get("/budget").text, "one triangle under every row was noise (2026-10-24)"


def test_the_home_bar_carries_the_tick_and_says_it_in_words(client, setup):
    move(client, setup["bank"], setup["food"], "30")
    page = client.get("/").text
    assert f'<b class="pace" style="left: {month_progress()}%"></b>' in page
    assert f"{month_progress()}% of the month has passed" in page
