import calendar
import re
from datetime import date, timedelta

from fastapi.testclient import TestClient

from .svc import plain


def test_dashboard_empty_state(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    assert "Net worth" not in response.text, "Home is one number now; net worth is in the reports"
    assert "Nothing recorded yet" in response.text
    assert date.today().strftime("%B") in response.text
    assert 'href="/transactions/new"' in response.text


def _words(html: str) -> str:
    """The text of a piece of page, tags gone and spaces tidied."""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def test_dashboard_shows_summary_and_recent_transactions(
    client: TestClient,
    root_accounts: dict[str, str],
    income_account: dict,
    expense_account: dict,
    svc,
):
    bank = client.post(
        "/api/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"},
    ).json()
    today = date.today().isoformat()
    for debit, credit, amount, payee in (
        (bank, income_account, "2500.00", "Employer"),
        (expense_account, bank, "120.50", "Supermarket"),
    ):
        response = client.post(
            "/api/transactions/",
            json={
                "date": today,
                "payee": payee,
                "postings": [
                    {"account": debit["aid"], "side": "debit", "amount": amount},
                    {"account": credit["aid"], "side": "credit", "amount": amount},
                ],
            },
        )
        assert response.status_code == 201

    text = client.get("/").text
    assert ">Spent<" in text and "120.50" in text  # no budget yet: what was spent this month
    strip = _words(text[text.index('class="home-strip"'):])
    assert "Earned ₹2,500.00" in strip and "Assigned ₹0.00" in strip and "Spent ₹120.50" in strip
    assert 'href="/budget?month=' in text and "Set up your budget" in text
    assert "Employer" in text and "Supermarket" in text
    assert plain(svc.reports.summary())["net_worth"] == "3379.50"  # 1000 + 2500 - 120.50


def test_dashboard_shows_what_is_left_to_spend_once_there_is_a_budget(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}
    ).json()
    client.put(f"/api/budget/categories/{expense_account['aid']}", json={"amount": "400"})
    client.post("/api/transactions/", json={"payee": "Shop", "postings": [
        {"account": expense_account["aid"], "side": "debit", "amount": "100"},
        {"account": bank["aid"], "side": "credit", "amount": "100"}]})
    text = " ".join(client.get("/").text.split())
    assert "Left to spend" in text and "300.00" in text
    assert "Spent 100.00 of 400.00" not in text, "the columns under the bar already say it"
    assert 'style="width: 25%"' in text


def test_dashboard_says_over_budget_when_a_category_is_overspent(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}
    ).json()
    client.put(f"/api/budget/categories/{expense_account['aid']}", json={"amount": "50"})
    client.post("/api/transactions/", json={"payee": "Shop", "postings": [
        {"account": expense_account["aid"], "side": "debit", "amount": "80"},
        {"account": bank["aid"], "side": "credit", "amount": "80"}]})
    text = " ".join(client.get("/").text.split())
    assert "Over budget" in text and '&minus;<span class="cur">&#8377;</span>30.00' in text and 'style="width: 100%"' in text


def test_dashboard_limits_recent_transactions(
    client: TestClient, account: dict, expense_account: dict
):
    for i in range(10):
        client.post(
            "/api/transactions/",
            json={
                "payee": f"tx-{i}",
                "postings": [
                    {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                    {"account": account["aid"], "side": "credit", "amount": "1.00"},
                ],
            },
        )
    text = client.get("/").text
    assert text.count('class="tx"') == 8


def test_friendly_date_filter():
    from app.templating import friendly_date

    today = date.today()
    assert friendly_date(today) == "Today"
    assert friendly_date(today - timedelta(days=1)) == "Yesterday"
    assert friendly_date(date(2020, 2, 3)) == "3 Feb 2020"
    assert friendly_date(date(today.year, 1, 1) if today.month > 1 or today.day > 2 else today) in (
        f"{date(today.year, 1, 1):%a}, 1 Jan",
        "Today",
    )


def test_onboarding_checklist_for_new_users(client: TestClient, root_accounts: dict[str, str]):
    text = client.get("/").text
    assert "Get started" in text
    assert f'href="/accounts/new?parent={root_accounts["Assets"]}"' in text
    assert f'href="/accounts/new?parent={root_accounts["Expenses"]}"' in text
    assert 'href="/transactions/new">Record your first transaction' in text


def test_onboarding_ticks_off_steps_and_ignores_opening_balances(
    client: TestClient, root_accounts: dict[str, str]
):
    bank = client.post(
        "/api/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"},
    ).json()
    text = client.get("/").text
    assert '<li class="done">' in text
    assert "Record your first transaction</a>" in text  # opening balance is not a recorded transaction

    food = client.post(
        "/api/accounts/", json={"name": "food", "parent_id": root_accounts["Expenses"]}
    ).json()
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": food["aid"], "side": "debit", "amount": "5.00"},
                {"account": bank["aid"], "side": "credit", "amount": "5.00"},
            ]
        },
    )
    assert "Get started" not in client.get("/").text


def test_money_filter_groups_digits_and_uses_a_true_minus():
    from decimal import Decimal

    from app.templating import money

    assert money(Decimal("1234567.5")) == "1,234,567.50"
    assert money("-2652.75") == "−2,652.75"
    assert money(None) == ""


def test_the_latest_entries_on_home_sit_under_a_transactions_heading(
    client: TestClient, account: dict, expense_account: dict
):
    client.post("/api/transactions/", json={"payee": "Shop", "postings": [
        {"account": expense_account["aid"], "side": "debit", "amount": "5"},
        {"account": account["aid"], "side": "credit", "amount": "5"}]})
    page = client.get("/").text
    assert "<h2>Transactions</h2>" in page and "<h2>Recent</h2>" not in page
    assert 'href="/transactions">View all</a>' in page


def test_the_i_on_home_shows_the_sum_with_the_persons_own_numbers(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}
    ).json()
    client.put(f"/api/budget/categories/{expense_account['aid']}", json={"amount": "400"})
    client.post("/api/transactions/", json={"payee": "Shop", "postings": [
        {"account": expense_account["aid"], "side": "debit", "amount": "100"},
        {"account": bank["aid"], "side": "credit", "amount": "100"}]})
    page = client.get("/").text
    assert 'aria-label="How what is left to spend is worked out"' in page
    sums = re.findall(r'<p class="calc-row-line([^"]*)"><span>([^<]*)</span><b>([^<]*)</b>', page)
    assert [(c.strip(), label, amount) for c, label, amount in sums] == [
        ("", "Carried in from earlier months", "₹0.00"),
        ("plus", f"Assigned in {calendar.month_name[date.today().month]}", "₹400.00"),
        ("minus", "Spent so far", "₹100.00"),
        ("total", "Left to spend", "₹300.00"),
    ]


def test_home_shows_one_box_with_earned_assigned_and_spent_and_a_warning_for_an_overspent_category(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict, income_account: dict
):
    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}
    ).json()
    client.put(f"/api/budget/categories/{expense_account['aid']}", json={"amount": "50"})
    for debit, credit, amount in ((expense_account, bank, "80"), (bank, income_account, "500")):
        client.post("/api/transactions/", json={"payee": "x", "postings": [
            {"account": debit["aid"], "side": "debit", "amount": amount},
            {"account": credit["aid"], "side": "credit", "amount": amount}]})
    page = client.get("/").text
    text = " ".join(page.split())
    strip = _words(page[page.index('class="home-strip"'):])
    assert "Earned ₹500.00" in strip and "Assigned ₹50.00" in strip and "Spent ₹80.00" in strip
    assert 'href="/summary?month=' in page[page.index('class="home-strip"') - 40:page.index('class="home-strip"') + 40], "the columns are one link to the month's summary"
    assert "home-tile" not in page and "Balance" not in page.split("<h2>Transactions</h2>")[0] and "Owed" not in page
    assert 'class="home-alert"' in page and f"<b>{expense_account['name']}</b> is over by ₹30.00" in text
    assert page.index('class="glance"') < page.index('class="home-strip"') < page.index('class="home-alert"') < page.index("<h2>Transactions</h2>"), "Transactions stay last"


def test_home_has_no_warning_when_nothing_is_overspent(client: TestClient, root_accounts: dict[str, str], expense_account: dict):
    client.post("/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"})
    client.put(f"/api/budget/categories/{expense_account['aid']}", json={"amount": "50"})
    client.post("/api/transactions/", json={"payee": "x", "postings": [
        {"account": expense_account["aid"], "side": "debit", "amount": "10"},
        {"account": client.get("/api/accounts/").json()[0]["aid"], "side": "credit", "amount": "10"}]})
    assert 'class="home-alert"' not in client.get("/").text


def test_the_month_pill_in_the_box_shows_another_month_and_never_a_future_one(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}
    ).json()
    today = date.today()
    last = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    for when, amount in ((last, "300"), (today, "100")):
        client.post("/api/transactions/", json={"date": when.isoformat(), "payee": "x", "postings": [
            {"account": expense_account["aid"], "side": "debit", "amount": amount},
            {"account": bank["aid"], "side": "credit", "amount": amount}]})
    now_html = client.get("/").text
    now = _words(now_html)
    assert 'class="month-input"' in now_html and f'max="{today:%Y-%m}"' in now_html
    assert "Spent ₹100.00" in now
    before_html = client.get("/", params={"month": f"{last:%Y-%m}"}).text
    before = _words(before_html)
    assert "Spent ₹300.00" in before and f"{last:%b} {last:%Y}" in before and 'class="pace"' not in before_html
    ahead = _words(client.get("/", params={"month": "2999-01"}).text)
    assert "Spent ₹100.00" in ahead, "a month that has not started opens this month"
