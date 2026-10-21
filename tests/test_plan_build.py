"""The Plan's Build section also takes a loan: paying its principal down is not spending (docs/developer/plan-design.md)."""

from datetime import date

import pytest

from .test_budget import account, assign, budget, identity, move


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False, saving=True, balance="1000000")
    interest = account(client, root_accounts, "Interest", "Expenses")
    return {"bank": bank, "loan": loan, "interest": interest, "roots": root_accounts}


def line(data):
    return next(l for l in data["saving"] if l["name"] == "Home Loan")


def test_a_loan_is_a_build_line_that_shows_what_is_still_owed(client, books):
    data = budget(client)
    assert line(data)["debt"] is True and line(data)["balance"] == "1000000.00", "owed, not the negative ledger balance"
    assert data["left_out_accounts"] == [], "not offered as an account to add to the budget"


def test_paying_principal_does_the_job_and_is_not_spending(client, books):
    assign(client, books["loan"], "8000")
    assert budget(client)["ready_to_assign"] == "92000.00"
    move(client, books["bank"], books["loan"], "8000")  # the principal
    data = budget(client)
    assert line(data)["activity"] == "8000.00" and line(data)["available"] == "0.00" and line(data)["balance"] == "992000.00"
    assert data["ready_to_assign"] == "92000.00" and data["activity"] == "0.00"
    identity(data)


def test_an_emi_split_into_principal_and_interest_spends_only_the_interest(client, books):
    r = client.post("/api/transactions/", json={"date": "2026-10-05", "postings": [
        {"account": books["loan"]["aid"], "amount": "8000", "side": "debit"},
        {"account": books["interest"]["aid"], "amount": "2000", "side": "debit"},
        {"account": books["bank"]["aid"], "amount": "10000", "side": "credit"},
    ]})
    assert r.status_code == 201, r.text
    data = budget(client, date(2026, 10, 1))
    assert line(data)["activity"] == "8000.00"
    interest = next(l for l in data["lines"] if l["name"] == "Interest")
    assert interest["activity"] == "2000.00", "interest is the real expense"
    identity(data)


def test_a_loan_cannot_have_a_payment_category_and_build_together(client, books):
    emi = account(client, books["roots"], "EMI", "Expenses")
    assert client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": emi["aid"]}).status_code == 400
    other = account(client, books["roots"], "Car Loan", "Liabilities", on_budget=False, payment_category_id=emi["aid"])
    switched = client.patch(f"/api/accounts/{other['aid']}", json={"saving": True})
    assert switched.status_code == 200 and switched.json()["payment_category_id"] is None


def test_the_web_page_words_a_loan_as_paid_down(client, books):
    move(client, books["bank"], books["loan"], "8000")
    text = " ".join(client.get("/plan?tab=build").text.split())
    assert "Home Loan" in text and "paid 8,000 " in text and "owed 9,92,000" in text
    sheet = client.get(f"/plan/category/{books['loan']['aid']}/sheet").text
    assert "Paid down" in sheet and "Still owed" in sheet and "to pay down" in sheet and "Moved in" not in sheet
