"""The head of Plans: one figure (what is left to spend) and a full-width bar, with Ready to assign as a quiet line under it."""

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
    page = client.get(f"/plan?month={MONTH}").text
    start = page.index("data-plan-head")
    end = page.find("data-ready-to-assign", start)
    return page[start: end if end > 0 else start + 3000], page


def test_the_head_says_what_is_left_to_spend_and_how_much_is_spent(client, books):
    assign(client, books["food"], "5000")
    move(client, books["bank"], books["food"], "1200")
    text, page = head(client)
    assert "Left to spend" in text and "3,800.00" in text and "Spent" in text and "1,200.00" in text and "5,000.00" in text
    assert 'class="glance-bar "' in text and "width: 24%" in text, "1,200 of 5,000, drawn across the whole head"
    assert "ready to assign" in page and 'data-ready-to-assign' in page


def test_the_head_turns_red_when_over_budget(client, books):
    assign(client, books["food"], "1000")
    move(client, books["bank"], books["food"], "1500")
    text, _ = head(client)
    assert "Over budget" in text and 'class="figure over"' in text and 'class="glance-bar over"' in text


def test_the_head_says_when_nothing_is_set_yet(client, books):
    text, _ = head(client)
    assert "Nothing assigned yet" in text


def test_every_rupee_has_a_job_replaces_the_pool_line_at_zero(client, books):
    assign(client, books["food"], "100000")
    _, page = head(client)
    assert "has a job" in page.split("data-ready-to-assign", 1)[1][:900]


def test_the_page_has_no_chips_and_no_other_sections(client, books):
    page = client.get(f"/plan?month={MONTH}").text
    assert 'aria-label="What to plan"' not in page and "/plan/configure" not in page
    assert client.get("/plan/configure").status_code == 404
