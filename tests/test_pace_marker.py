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


def test_the_budget_bars_carry_the_tick_for_the_current_month_only(client, setup):
    page = client.get("/plan").text
    pace = month_progress()
    assert f'<b class="pace" style="left: {pace}%"></b>' in page
    last = (date.today().replace(day=1)).replace(year=date.today().year - 1)
    assert 'class="pace"' not in client.get(f"/plan?month={last:%Y-%m}").text, "other months have no today"


def test_the_home_bar_carries_the_tick_and_says_it_in_words(client, setup):
    move(client, setup["bank"], setup["food"], "30")
    page = client.get("/").text
    assert f'<b class="pace" style="left: {month_progress()}%"></b>' in page
    assert f"{month_progress()}% of the month has passed" in page
