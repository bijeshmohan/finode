"""The month summary: income and spending for a month, per top-level account, with six months of totals."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.clock import local_today

from .svc import plain

THIS_MONTH = local_today().replace(day=1)


def shift(month: date, by: int) -> date:
    index = month.year * 12 + month.month - 1 + by
    return date(index // 12, index % 12 + 1, 1)


def make(client, name, parent):
    response = client.post("/api/accounts/", json={"name": name, "parent_id": parent})
    assert response.status_code == 201, response.text
    return response.json()


def post(client, debit, credit, amount, when):
    response = client.post(
        "/api/transactions/",
        json={
            "date": when.isoformat(),
            "postings": [
                {"account": debit["aid"], "side": "debit", "amount": amount},
                {"account": credit["aid"], "side": "credit", "amount": amount},
            ],
        },
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def books(client, root_accounts):
    bank = make(client, "Bank", root_accounts["Assets"])
    savings = make(client, "Savings", root_accounts["Assets"])
    salary = make(client, "Salary", root_accounts["Income"])
    food = make(client, "Food", root_accounts["Expenses"])
    groceries = make(client, "Groceries", food["aid"])
    dining = make(client, "Dining", food["aid"])
    rent = make(client, "Rent", root_accounts["Expenses"])
    now, last, before = THIS_MONTH, shift(THIS_MONTH, -1), shift(THIS_MONTH, -2)
    for month, pay in ((now, "5000"), (last, "6000"), (before, "4000")):
        post(client, bank, salary, pay, month)
    post(client, groceries, bank, "400", now)
    post(client, dining, bank, "100", now)
    post(client, rent, bank, "1500", now)
    post(client, groceries, bank, "300", last)
    post(client, rent, bank, "1500", last)
    post(client, savings, bank, "999", now)  # a transfer is neither income nor spending
    post(client, rent, bank, "777", shift(THIS_MONTH, -7))  # older than the six months shown
    return {"bank": bank}


def report(svc, month=None):
    return plain(svc.reports.month_report(month))


def test_the_current_month(client, books, svc):
    data = report(svc)
    assert data["month"] == THIS_MONTH.isoformat() and data["period_end"] == local_today().isoformat()
    assert (data["income"], data["expenses"], data["net"]) == ("5000.00", "2000.00", "3000.00")
    assert data["savings_rate"] == "60.0"
    assert (data["previous_income"], data["previous_expenses"]) == ("6000.00", "1800.00")
    assert "unpriced" not in data


def test_spending_is_per_top_level_account_against_last_month(client, books, svc):
    data = report(svc)
    assert [(l["account"], l["amount"], l["previous"], l["share"]) for l in data["spending"]] == [
        ("Rent", "1500.00", "1500.00", "75.0"),
        ("Food", "500.00", "300.00", "25.0"),  # Groceries and Dining together
    ]
    assert [(l["account"], l["amount"], l["previous"], l["share"]) for l in data["earnings"]] == [
        ("Salary", "5000.00", "6000.00", "100.0")
    ]


def test_an_earlier_month_and_any_day_in_it(client, books, svc):
    last = shift(THIS_MONTH, -1)
    data = report(svc, last.replace(day=15))
    assert data["month"] == last.isoformat() and data["period_end"] == (THIS_MONTH - timedelta(days=1)).isoformat()
    assert (data["income"], data["expenses"], data["net"]) == ("6000.00", "1800.00", "4200.00")
    assert {l["account"]: l["amount"] for l in data["spending"]} == {"Rent": "1500.00", "Food": "300.00"}


def test_the_trend_is_the_last_six_months_oldest_first(client, books, svc):
    trend = report(svc)["trend"]
    assert [t["month"] for t in trend] == [shift(THIS_MONTH, -i).isoformat() for i in (5, 4, 3, 2, 1, 0)]
    assert [(t["income"], t["expenses"], t["net"]) for t in trend[3:]] == [
        ("4000.00", "0.00", "4000.00"),
        ("6000.00", "1800.00", "4200.00"),
        ("5000.00", "2000.00", "3000.00"),
    ]
    assert all(t["income"] == t["expenses"] == "0.00" for t in trend[:3])  # and the 777 from seven months ago is not in it


def test_the_trend_ends_with_the_month_asked_for(client, books, svc):
    trend = report(svc, shift(THIS_MONTH, -1))["trend"]
    assert trend[-1]["month"] == shift(THIS_MONTH, -1).isoformat() and trend[-1]["income"] == "6000.00"


def test_spending_beyond_income_is_a_negative_rate(client, root_accounts, svc):
    bank = make(client, "Bank", root_accounts["Assets"])
    salary = make(client, "Salary", root_accounts["Income"])
    rent = make(client, "Rent", root_accounts["Expenses"])
    post(client, bank, salary, "1000", THIS_MONTH)
    post(client, rent, bank, "1500", THIS_MONTH)
    data = report(svc)
    assert data["net"] == "-500.00" and data["savings_rate"] == "-50.0"


def test_no_income_gives_no_rate(client, root_accounts, svc):
    bank = make(client, "Bank", root_accounts["Assets"])
    rent = make(client, "Rent", root_accounts["Expenses"])
    post(client, rent, bank, "50", THIS_MONTH)
    data = report(svc)
    assert data["savings_rate"] is None and data["expenses"] == "50.00"


def test_an_empty_ledger(client, root_accounts, svc):
    data = report(svc)
    assert (data["income"], data["expenses"]) == ("0.00", "0.00") and data["spending"] == [] and len(data["trend"]) == 6


def test_a_month_that_has_not_started_is_refused(svc):
    with pytest.raises(ValueError, match="not started"):
        svc.reports.month_report(shift(THIS_MONTH, 1))


# ---- the page ------------------------------------------------------------------------------------------------------


def squash(text: str) -> str:
    import re

    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


def test_the_page(client, books):
    page = client.get("/summary")
    assert page.status_code == 200
    text = squash(page.text)
    assert "so far" in text and "5,000.00" in text and "2,000.00" in text and "3,000.00" in text
    assert "You kept 60.0% of what came in." in text
    # a month still running is not compared with a whole one: last month is shown in full instead
    assert "Rent" in text and "75.0% of spending" in text and "300.00 in all of last month" in text  # Food
    assert "Spending so far; last month: 1,800.00." in text
    assert "Where it came from" in text and "Salary" in text and "6,000.00 in all of last month" in text
    assert f"/summary?month={shift(THIS_MONTH, -1):%Y-%m}" in page.text
    assert 'title="Next month"' not in page.text, "there is nothing after the current month"
    assert page.text.count('class="bars"') == 6


def test_an_earlier_month_has_a_way_forward(client, books):
    last = shift(THIS_MONTH, -1)
    page = client.get(f"/summary?month={last:%Y-%m}")
    assert page.status_code == 200 and 'title="Next month"' in page.text and "so far" not in page.text
    assert "6,000.00" in page.text
    assert "Food" in squash(page.text) and "300.00 in all of last month" not in squash(page.text)  # whole months are compared
    assert "new" in squash(page.text)  # Food and Rent had nothing the month before


def test_a_future_month_goes_back_to_this_one(client, books):
    response = client.get(f"/summary?month={shift(THIS_MONTH, 2):%Y-%m}", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/summary?month={THIS_MONTH:%Y-%m}"


def test_an_empty_page_says_so(client, root_accounts):
    text = squash(client.get("/summary").text)
    assert "Nothing recorded in these months yet." in text and "No spending recorded yet this month." in text


def test_the_dashboard_links_to_it(client, books):
    assert 'href="/summary"' in client.get("/").text
