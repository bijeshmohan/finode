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
    assert "120.50" in text  # no budget yet: what was spent this month
    assert "home-strip" not in text, "no Earned / Assigned / Spent columns"
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
    client.post(
        "/api/transactions/",
        json={
            "payee": "Shop",
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "100"},
                {"account": bank["aid"], "side": "credit", "amount": "100"},
            ],
        },
    )
    text = " ".join(client.get("/").text.split())
    assert "Left to spend" in text and "300.00" in text
    assert "Spent so far 100.00 of 400.00" in text, "a caption under the bar says what it shows"
    assert 'style="width: 25%"' in text


def test_dashboard_says_over_budget_when_a_category_is_overspent(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}
    ).json()
    client.put(f"/api/budget/categories/{expense_account['aid']}", json={"amount": "50"})
    client.post(
        "/api/transactions/",
        json={
            "payee": "Shop",
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "80"},
                {"account": bank["aid"], "side": "credit", "amount": "80"},
            ],
        },
    )
    text = " ".join(client.get("/").text.split())
    assert (
        "Over budget" in text
        and '&minus;<span class="cur">&#8377;</span>30.00' in text
        and 'style="width: 100%"' in text
    )


def _spend(client, expense_account, account, payee, day):
    response = client.post(
        "/api/transactions/",
        json={
            "payee": payee,
            "date": day,
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "1.00"},
                {"account": account["aid"], "side": "credit", "amount": "1.00"},
            ],
        },
    )
    assert response.status_code == 201, response.text


def test_home_shows_a_few_and_show_more_brings_the_rest_of_the_month(
    client: TestClient, account: dict, expense_account: dict
):
    for i in range(1, 13):
        _spend(client, expense_account, account, f"tx-{i}", f"2026-01-{i:02d}")
    text = client.get("/", params={"month": "2026-01"}).text
    assert text.count('class="tx"') == 8 and "Show 4 more" in text and "4 left" in text
    url = re.search(r'hx-get="(/transactions/more[^"]*)"', text).group(1).replace("&amp;", "&")
    more = client.get(url).text
    assert (
        more.count('class="tx"') == 4
        and "Show" not in more.replace("Show more", "")
        and "That is all of January · 12 transactions" in more
    )
    assert "tx-12" not in more and "tx-1<" in more.replace("tx-1</", "tx-1<"), "the older ones come next"


def test_a_day_is_never_split_between_two_chunks(client: TestClient, account: dict, expense_account: dict):
    for i in range(10):
        _spend(client, expense_account, account, f"same-{i}", "2026-01-05")  # ten entries on one day
    _spend(client, expense_account, account, "older", "2026-01-02")
    text = client.get("/", params={"month": "2026-01"}).text
    assert text.count('class="tx"') == 10 and "Show 1 more" in text, "the first chunk runs on to the end of its day"


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
    assert 'href="/transactions/new">Record your first spend' in text
    assert 'href="/budget">Give your money a job' in text


def test_onboarding_ticks_off_steps_and_ignores_opening_balances(client: TestClient, root_accounts: dict[str, str]):
    bank = client.post(
        "/api/accounts/",
        json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100.00"},
    ).json()
    text = client.get("/").text
    assert '<li class="done">' in text
    assert "Record your first spend</a>" in text  # opening balance is not a recorded transaction

    food = client.post("/api/accounts/", json={"name": "food", "parent_id": root_accounts["Expenses"]}).json()
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": food["aid"], "side": "debit", "amount": "5.00"},
                {"account": bank["aid"], "side": "credit", "amount": "5.00"},
            ]
        },
    )
    assert "Get started · 2 of 3" in client.get("/").text, "the card stays until the budget has a job for the money"


def test_money_filter_groups_digits_and_uses_a_true_minus():
    from decimal import Decimal

    from app.templating import money

    assert money(Decimal("1234567.5")) == "1,234,567.50"
    assert money("-2652.75") == "−2,652.75"
    assert money(None) == ""


def test_the_latest_entries_on_home_sit_under_a_transactions_heading(
    client: TestClient, account: dict, expense_account: dict
):
    client.post(
        "/api/transactions/",
        json={
            "payee": "Shop",
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "5"},
                {"account": account["aid"], "side": "credit", "amount": "5"},
            ],
        },
    )
    page = client.get("/").text
    assert "<h2>Transactions</h2>" in page and "<h2>Recent</h2>" not in page
    assert 'href="/transactions?month=' + date.today().strftime("%Y-%m") + '">View all ›</a>' in page


def test_the_i_on_home_shows_the_sum_with_the_persons_own_numbers(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}
    ).json()
    client.put(f"/api/budget/categories/{expense_account['aid']}", json={"amount": "400"})
    client.post(
        "/api/transactions/",
        json={
            "payee": "Shop",
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "100"},
                {"account": bank["aid"], "side": "credit", "amount": "100"},
            ],
        },
    )
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
        client.post(
            "/api/transactions/",
            json={
                "payee": "x",
                "postings": [
                    {"account": debit["aid"], "side": "debit", "amount": amount},
                    {"account": credit["aid"], "side": "credit", "amount": amount},
                ],
            },
        )
    page = client.get("/").text
    text = " ".join(page.split())
    assert "home-strip" not in page
    assert 'href="/summary' not in page, "the Summary page is gone"
    assert "home-tile" not in page and "Balance" not in page.split("<h2>Transactions</h2>")[0] and "Owed" not in page
    assert "home-alert" not in page and "is over by" not in text, "no overspent warning on Home (removed 2026-10-24)"
    assert page.index('class="glance"') < page.index("<h2>Transactions</h2>"), "Transactions stay last"


def test_the_month_pill_in_the_box_shows_another_month_and_never_a_future_one(
    client: TestClient, root_accounts: dict[str, str], expense_account: dict
):
    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "1000.00"}
    ).json()
    today = date.today()
    last = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    for when, amount in ((last, "300"), (today, "100")):
        client.post(
            "/api/transactions/",
            json={
                "date": when.isoformat(),
                "payee": "x",
                "postings": [
                    {"account": expense_account["aid"], "side": "debit", "amount": amount},
                    {"account": bank["aid"], "side": "credit", "amount": amount},
                ],
            },
        )
    now_html = client.get("/").text
    now = _words(now_html)
    assert 'class="month-input"' in now_html and f'max="{today:%Y-%m}"' in now_html
    assert "100.00" in now
    before_html = client.get("/", params={"month": f"{last:%Y-%m}"}).text
    before = _words(before_html)
    assert "300.00" in before and f"{last:%b} {last:%Y}" in before and 'class="pace"' not in before_html
    rows = before_html[before_html.index("<h2>Transactions</h2>") :]
    assert "300.00" in rows and "100.00" not in rows, "an older month lists its own entries, not the latest ones"
    empty = client.get("/", params={"month": f"{(last - timedelta(days=40)):%Y-%m}"}).text
    assert "Nothing was recorded in" in empty and "Nothing recorded yet" not in empty, (
        "an empty month keeps the box and the page"
    )
    assert f'href="/transactions?month={last:%Y-%m}"' in before_html
    ahead = _words(client.get("/", params={"month": "2999-01"}).text)
    assert "100.00" in ahead, "a month that has not started opens this month"


def test_the_checklist_stays_on_home_after_the_first_entry_until_the_plan_is_used(
    client: TestClient, root_accounts, monkeypatch
):
    """Everybody keeps seeing the card until all three steps are done."""

    bank = client.post(
        "/api/accounts/", json={"name": "bank", "parent_id": root_accounts["Assets"], "balance": "100"}
    ).json()
    food = client.post("/api/accounts/", json={"name": "food", "parent_id": root_accounts["Expenses"]}).json()
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": food["aid"], "side": "debit", "amount": "5"},
                {"account": bank["aid"], "side": "credit", "amount": "5"},
            ]
        },
    )
    text = client.get("/").text
    assert "Get started · 2 of 3" in text and "Give your money a job</a>" in text
    assert "Open Budgets and set aside rent and food" in text
    client.put(
        f"/api/budget/categories/{food['aid']}", json={"month": date.today().replace(day=1).isoformat(), "amount": "50"}
    )
    assert "Get started" not in client.get("/").text
