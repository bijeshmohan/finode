"""Each chip of Plans has its own head: one figure and a full-width bar that answer that chip's question."""

from datetime import date

import pytest

from .test_budget import account, assign, move

MONTH = date.today().strftime("%Y-%m")


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    fund = account(client, root_accounts, "Mutual Funds", "Assets", on_budget=False, saving=True)
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False, saving=True, balance="500000")
    food = account(client, root_accounts, "Food", "Expenses")
    salary = account(client, root_accounts, "Salary", "Income")
    return {"bank": bank, "fund": fund, "loan": loan, "food": food, "salary": salary}


def head(client, tab):
    page = client.get(f"/plan?month={MONTH}&tab={tab}").text
    mark = f'data-plan-head="{tab}"'
    assert mark in page, tab
    start = page.index(mark)
    end = page.find("data-ready-to-assign", start)
    return page[start: end if end > 0 else start + 3000], page


def test_spend_head_says_what_is_left_to_spend_and_how_much_is_spent(client, books):
    assign(client, books["food"], "5000")
    move(client, books["bank"], books["food"], "1200")
    text, page = head(client, "spend")
    assert "Left to spend" in text and "3,800.00" in text and "Spent" in text and "1,200.00" in text and "5,000.00" in text
    assert 'class="glance-bar "' in text and "width: 24%" in text, "1,200 of 5,000, drawn across the whole head"
    assert "ready to assign" in page and 'data-ready-to-assign' in page


def test_spend_head_turns_red_when_over_budget(client, books):
    assign(client, books["food"], "1000")
    move(client, books["bank"], books["food"], "1500")
    text, _ = head(client, "spend")
    assert "Over budget" in text and 'class="figure over"' in text and 'class="glance-bar over"' in text


def test_build_head_is_moved_against_planned_and_names_what_is_still_owed(client, books):
    assign(client, books["fund"], "9000")
    move(client, books["bank"], books["fund"], "6500")
    text, page = head(client, "build")
    assert "Left to build" in text and "2,500.00" in text and "Moved" in text and "6,500.00" in text and "9,000.00" in text
    assert "5,00,000.00 still owed on loans" in page.split("data-ready-to-assign", 1)[1][:900]


def test_build_head_is_green_and_says_above_plan_when_more_was_moved(client, books):
    assign(client, books["fund"], "5000")
    move(client, books["bank"], books["fund"], "8000")
    text, _ = head(client, "build")
    assert "Above plan" in text and 'class="figure above"' in text and 'class="glance-bar above"' in text and "3,000.00" in text


def test_earn_head_is_what_is_still_to_come_without_the_pool_or_the_badge(client, books):
    assign(client, books["salary"], "85000")
    client.post("/api/transactions/", json={"postings": [
        {"account": books["bank"]["aid"], "side": "debit", "amount": "62000"},
        {"account": books["salary"]["aid"], "side": "credit", "amount": "62000"}]})
    text, page = head(client, "earn")
    assert "Still to come" in text and "23,000.00" in text and "Received" in text and "62,000.00" in text and "85,000.00" in text
    assert 'class="glance-bar "' in text and 'class="figure "' in text, "dark until more came in than was expected"
    assert "data-ready-to-assign" not in page, "Earn never touches the pool"
    assert "Needs you" not in text


def test_the_head_says_when_nothing_is_set_yet(client, books):
    for tab, words in (("spend", "Nothing assigned yet"), ("build", "Nothing planned yet"), ("earn", "Nothing expected yet")):
        text, _ = head(client, tab)
        assert words in text, tab


def test_every_rupee_has_a_job_replaces_the_pool_line_at_zero(client, books):
    assign(client, books["food"], "100000")
    _, page = head(client, "spend")
    assert "has a job" in page.split("data-ready-to-assign", 1)[1][:900]


def test_earn_head_turns_green_only_when_more_came_in_than_was_expected(client, books):
    assign(client, books["salary"], "50000")
    def receive(amount):
        client.post("/api/transactions/", json={"postings": [
            {"account": books["bank"]["aid"], "side": "debit", "amount": amount},
            {"account": books["salary"]["aid"], "side": "credit", "amount": amount}]})
    receive("50000")  # exactly what was expected: not above
    text, _ = head(client, "earn")
    assert 'class="glance-bar "' in text and "Still to come" in text
    receive("5000")
    text, _ = head(client, "earn")
    assert "Above expected" in text and 'class="glance-bar above"' in text and 'class="figure above"' in text and "5,000.00" in text
