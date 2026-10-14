"""Paying a loan that is outside the budget: the EMI spends the category the loan points at."""

from datetime import date

import pytest

from .test_budget import account, assign, budget, line, move


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False)
    emi = account(client, root_accounts, "EMI", "Expenses")
    interest = account(client, root_accounts, "Interest", "Expenses")
    return {"bank": bank, "loan": loan, "emi": emi, "interest": interest}


def point(client, loan, category):
    response = client.patch(f"/api/accounts/{loan['aid']}", json={"payment_category_id": category["aid"] if category else None})
    assert response.status_code == 200, response.text
    return response.json()


def test_without_a_category_the_emi_just_lowers_ready_to_assign(client, books):
    assign(client, books["emi"], "15000")
    move(client, books["bank"], books["loan"], "15000")  # EMI: debits the loan, credits the bank
    data = budget(client)
    assert line(data, "EMI")["activity"] == "0.00" and line(data, "EMI")["available"] == "15000.00"
    assert data["ready_to_assign"] == "70000.00", "the EMI left the bank and the envelope still holds 15000"


def test_with_a_category_the_emi_spends_it(client, books):
    point(client, books["loan"], books["emi"])
    assign(client, books["emi"], "15000")
    move(client, books["bank"], books["loan"], "15000")
    data = budget(client)
    emi = line(data, "EMI")
    assert emi["activity"] == "15000.00" and emi["available"] == "0.00"
    assert data["ready_to_assign"] == "85000.00", "assigned and spent: nothing else changes"


def test_interest_the_lender_charges_stays_outside_the_budget(client, books):
    point(client, books["loan"], books["emi"])
    move(client, books["loan"], books["interest"], "900")  # the lender charges interest to the loan
    data = budget(client)
    assert line(data, "Interest")["activity"] == "0.00"
    assert data["left_out_accounts"] == [] and data["left_out"] == "0.00", "no nudge to add the loan to the budget"


def test_borrowing_into_the_bank_is_not_spending(client, books):
    point(client, books["loan"], books["emi"])
    move(client, books["loan"], books["bank"], "50000")  # the loan pays out: credit the loan, debit the bank
    data = budget(client)
    assert line(data, "EMI")["activity"] == "0.00" and data["ready_to_assign"] == "150000.00"


def test_a_split_emi_counts_both_parts(client, books):
    point(client, books["loan"], books["emi"])
    client.post("/api/transactions/", json={"postings": [
        {"account": books["loan"]["aid"], "side": "debit", "amount": "8000"},
        {"account": books["interest"]["aid"], "side": "debit", "amount": "2000"},
        {"account": books["bank"]["aid"], "side": "credit", "amount": "10000"},
    ]})
    data = budget(client)
    assert line(data, "EMI")["activity"] == "8000.00" and line(data, "Interest")["activity"] == "2000.00"
    assert data["cash"] == "90000.00" and data["available"] == "-10000.00", "overspent in its own month: Ready to Assign changes next month"


def test_the_rules_for_choosing_a_category(client, books, root_accounts):
    url = f"/api/accounts/{books['loan']['aid']}"
    assert client.patch(url, json={"payment_category_id": books["bank"]["aid"]}).status_code == 400
    assert client.patch(f"/api/accounts/{books['emi']['aid']}", json={"payment_category_id": books["emi"]["aid"]}).status_code == 400
    assert client.patch(f"/api/accounts/{books['bank']['aid']}", json={"payment_category_id": books["emi"]["aid"]}).status_code == 400, "already part of the budget"
    assert client.patch(url, json={"payment_category_id": root_accounts["Expenses"]}).status_code == 400


def test_joining_the_budget_drops_the_category_and_it_can_be_cleared(client, books):
    point(client, books["loan"], books["emi"])
    assert client.get(f"/api/accounts/{books['loan']['aid']}").json()["payment_category_id"] == books["emi"]["aid"]
    assert point(client, books["loan"], None)["payment_category_id"] is None
    point(client, books["loan"], books["emi"])
    joined = client.patch(f"/api/accounts/{books['loan']['aid']}", json={"on_budget": True}).json()
    assert joined["on_budget"] and joined["payment_category_id"] is None


def test_deleting_the_category_clears_the_link(client, books):
    point(client, books["loan"], books["emi"])
    assert client.delete(f"/api/accounts/{books['emi']['aid']}").status_code in (200, 204)
    assert client.get(f"/api/accounts/{books['loan']['aid']}").json()["payment_category_id"] is None


def test_the_edit_page_offers_and_saves_it(client, books):
    page = client.get(f"/accounts/{books['loan']['aid']}/edit").text
    assert "Budget payments to this account under" in page and ">EMI</option>" in page
    saved = client.post(f"/accounts/{books['loan']['aid']}/edit", data={
        "name": "Home Loan", "budget_choice": "1", "payment_category": books["emi"]["aid"],
    })
    assert saved.status_code == 200 and saved.headers["HX-Redirect"].startswith("/accounts/")
    assert client.get(f"/api/accounts/{books['loan']['aid']}").json()["payment_category_id"] == books["emi"]["aid"]
    assert f'value="{books["emi"]["aid"]}" selected' in client.get(f"/accounts/{books['loan']['aid']}/edit").text
    client.post(f"/accounts/{books['loan']['aid']}/edit", data={"name": "Home Loan", "budget_choice": "1", "payment_category": ""})
    assert client.get(f"/api/accounts/{books['loan']['aid']}").json()["payment_category_id"] is None
    assert client.post(f"/accounts/{books['loan']['aid']}/edit", data={
        "name": "Home Loan", "budget_choice": "1", "payment_category": books["bank"]["aid"],
    }).status_code == 400
