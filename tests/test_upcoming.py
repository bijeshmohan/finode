"""Entries dated ahead are not history: out of Home's recent list, and in their own row on the transactions page."""

from datetime import timedelta

import pytest

from app.clock import local_today

from .books import post_account


@pytest.fixture
def ledger(client, root_accounts):
    def make(name, parent, **extra):
        return post_account(client, {"name": name, "parent_id": parent, **extra}).json()["id"]

    bank = make("Bank", root_accounts["Assets"], balance="5000")
    loan = make("Bicycle loan", root_accounts["Liabilities"])
    return bank, loan


def record(client, bank, loan, payee, on):
    r = client.post(
        "/api/transactions/",
        json={
            "date": on.isoformat(),
            "payee": payee,
            "postings": [
                {"account_id": loan, "side": "debit", "amount": "100"},
                {"account_id": bank, "side": "credit", "amount": "100"},
            ],
        },
    )
    assert r.status_code == 201, r.text


def view(client, path="/api/views/transactions", **params) -> dict:
    answer = client.get(path, params=params)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_home_leaves_out_what_is_dated_ahead(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "Paid already", local_today())
    record(client, bank, loan, "EMI next month", local_today() + timedelta(days=40))
    titles = [r["title"] for r in view(client)["rows"]]  # Home lists the Transactions view's rows
    assert "Paid already" in titles and "EMI next month" not in titles


def test_the_transactions_list_keeps_them_apart_soonest_first(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "Paid already", local_today())
    for i, days in enumerate((40, 10, 70)):
        record(client, bank, loan, f"EMI {i}", local_today() + timedelta(days=days))
    seen = view(client)
    assert [u["title"] for u in seen["upcoming"]] == ["EMI 1", "EMI 0", "EMI 2"], "soonest first"
    titles = [r["title"] for r in seen["rows"]]
    assert "Paid already" in titles and not [t for t in titles if t.startswith("EMI")], "the list is history only"


def test_a_search_finds_what_is_dated_ahead_too(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "EMI later", local_today() + timedelta(days=20))
    seen = view(client, q="EMI later")
    assert [u["title"] for u in seen["upcoming"]] == ["EMI later"] and seen["rows"] == []


def test_later_pages_have_no_upcoming(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "EMI later", local_today() + timedelta(days=20))
    assert view(client)["upcoming"] and view(client, offset=25)["upcoming"] == []


def test_the_upcoming_total_is_what_the_schedule_comes_to(client, ledger):
    bank, loan = ledger
    for days in (10, 40):
        record(client, bank, loan, "EMI", local_today() + timedelta(days=days))
    seen = view(client)
    assert len(seen["upcoming"]) == 2 and seen["upcoming_total"] == "200.00"


def test_no_total_when_money_in_is_mixed_with_money_out(client, ledger, root_accounts):
    bank, loan = ledger
    salary = post_account(client, {"name": "Salary", "parent_id": root_accounts["Income"]}).json()["id"]
    record(client, bank, loan, "EMI", local_today() + timedelta(days=10))
    client.post(
        "/api/transactions/",
        json={
            "date": (local_today() + timedelta(days=12)).isoformat(),
            "payee": "Pay",
            "postings": [
                {"account_id": bank, "side": "debit", "amount": "900"},
                {"category_id": salary, "side": "credit", "amount": "900"},
            ],
        },
    )
    listed = view(client)
    assert len(listed["upcoming"]) == 2 and listed["upcoming_total"] is None
    on_bank = view(client, f"/api/views/accounts/{bank}")
    assert on_bank["upcoming_total"] is None and {u["title"]: u["income"] for u in on_bank["upcoming"]} == {
        "EMI": False,
        "Pay": True,
    }, "money coming in is marked"


def test_an_account_page_keeps_what_is_dated_ahead_out_of_its_activity(client, ledger):
    bank, loan = ledger
    record(client, bank, loan, "Paid already", local_today())
    assert view(client, f"/api/views/accounts/{bank}")["upcoming"] == [], "nothing ahead: no card"
    for i, days in enumerate((40, 10)):
        record(client, bank, loan, f"EMI {i}", local_today() + timedelta(days=days))
    seen = view(client, f"/api/views/accounts/{bank}")
    assert [u["title"] for u in seen["upcoming"]] == ["EMI 1", "EMI 0"] and seen["upcoming_total"] == "200.00"
    titles = [r["title"] for r in seen["entries"]]
    assert "Paid already" in titles and not [t for t in titles if t.startswith("EMI")], "history only"


def test_a_category_page_only_lists_what_has_happened(client, ledger, root_accounts):
    bank, _ = ledger
    food = post_account(client, {"name": "Food", "parent_id": root_accounts["Expenses"]}).json()["id"]
    for payee, days in (("Lunch", 0), ("Dinner next week", 7)):
        client.post(
            "/api/transactions/",
            json={
                "date": (local_today() + timedelta(days=days)).isoformat(),
                "payee": payee,
                "postings": [
                    {"category_id": food, "side": "debit", "amount": "50"},
                    {"account_id": bank, "side": "credit", "amount": "50"},
                ],
            },
        )
    assert [r["title"] for r in view(client, f"/api/views/categories/{food}")["entries"]] == ["Lunch"]
