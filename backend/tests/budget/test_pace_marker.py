"""The tick that shows how far through the month today is, on the bars of the current month."""

from datetime import date

import pytest

from finode.clock import month_progress
from tests.budget.test_budget import account, assign


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
