"""Reports speak two languages: by category (what the money was for, as the budget counts it) and by account (the
books: paying into a loan is no expense)."""

import pytest

from .test_budget import account
from .test_budget_categories import paid


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False)
    emi = account(client, root_accounts, "EMI", "Expenses")
    food = account(client, root_accounts, "Food", "Expenses")
    salary = account(client, root_accounts, "Salary", "Income")
    return {"bank": bank, "loan": loan, "emi": emi, "food": food, "salary": salary}


def breakdown(client, **params):
    response = client.get("/api/reports/breakdown", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_breakdown_is_by_category_unless_asked_by_account(client, books):
    paid(client, books["bank"], books["loan"], "1000", books["emi"])  # labelled for EMI, no payment link needed
    paid(client, books["bank"], books["food"], "200")
    by_category = breakdown(client)
    assert by_category["total"] == "1200.00"
    assert [(l["account"], l["amount"]) for l in by_category["lines"]] == [("EMI", "1000.00"), ("Food", "200.00")]
    by_account = breakdown(client, by="account")
    assert by_account["total"] == "200.00" and [l["account"] for l in by_account["lines"]] == ["Food"]


def test_income_is_by_category_too(client, books):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": books["bank"]["aid"], "side": "debit", "amount": "900"},
                {"account": books["salary"]["aid"], "side": "credit", "amount": "900"},
            ]
        },
    )
    income = breakdown(client, kind="income")
    assert income["total"] == "900.00" and income["lines"][0]["account"] == "Salary"


def test_the_summary_has_the_books_expenses_and_the_budgets_spending(client, books):
    paid(client, books["bank"], books["loan"], "1000", books["emi"])
    paid(client, books["bank"], books["food"], "200")
    summary = client.get("/api/reports/summary").json()
    assert (summary["expenses"], summary["spent"], summary["net_income"]) == ("200.00", "1200.00", "-200.00")


def test_a_category_page_lists_the_loan_payments_labelled_for_it(client, books):
    paid(client, books["bank"], books["loan"], "1000", books["emi"])
    entries = client.get(f"/api/accounts/{books['emi']['aid']}/register").json()
    assert [e["change"] for e in entries] == ["1000.00"] and entries[0]["counter_accounts"][0] in ("Home Loan", "Bank")


def test_a_category_cannot_be_put_on_a_line_to_a_budget_account(client, books):
    response = client.post(
        "/api/transactions/",
        json={
            "postings": [
                {"account": books["food"]["aid"], "side": "debit", "amount": "5"},
                {"account": books["bank"]["aid"], "side": "credit", "amount": "5", "category": books["food"]["aid"]},
            ]
        },
    )
    assert response.status_code == 400 and "part of the budget" in response.text


def test_the_breakdown_refuses_an_unknown_lens(client, books):
    assert client.get("/api/reports/breakdown", params={"by": "colour"}).status_code == 422
