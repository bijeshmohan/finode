"""The budget reads categories: what a line says it was for is what the budget counts, whatever kind of account the
line is on, and a loan's payment category keeps its lines in step."""

import pytest

from .test_budget import account, assign, budget, line


def paid(client, bank, to, amount, category=None):
    posting = {"account": to["aid"], "side": "debit", "amount": amount}
    if category:
        posting["category"] = category["aid"]
    response = client.post(
        "/api/transactions/",
        json={"postings": [posting, {"account": bank["aid"], "side": "credit", "amount": amount}]},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False)
    emi = account(client, root_accounts, "EMI", "Expenses")
    sip = account(client, root_accounts, "SIP", "Expenses")
    return {"bank": bank, "loan": loan, "emi": emi, "sip": sip}


def test_a_line_that_names_its_category_spends_it_without_any_payment_link(client, books):
    assign(client, books["emi"], "15000")
    paid(client, books["bank"], books["loan"], "15000", books["emi"])
    emi = line(budget(client), "EMI")
    assert emi["activity"] == "15000.00" and emi["available"] == "0.00"


def test_the_same_account_can_spend_different_categories_on_different_days(client, books):
    paid(client, books["bank"], books["loan"], "100", books["emi"])
    paid(client, books["bank"], books["loan"], "40", books["sip"])
    data = budget(client)
    assert (line(data, "EMI")["activity"], line(data, "SIP")["activity"]) == ("100.00", "40.00")


def test_pointing_a_loan_at_a_category_counts_the_payments_already_made(client, books):
    paid(client, books["bank"], books["loan"], "700")
    assert line(budget(client), "EMI")["activity"] == "0.00"
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": books["emi"]["aid"]})
    assert line(budget(client), "EMI")["activity"] == "700.00"
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": books["sip"]["aid"]})
    data = budget(client)
    assert (line(data, "EMI")["activity"], line(data, "SIP")["activity"]) == ("0.00", "700.00")
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": None})
    assert line(budget(client), "SIP")["activity"] == "0.00"


def test_a_label_the_person_chose_survives_a_change_of_the_loans_category(client, books):
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": books["emi"]["aid"]})
    paid(client, books["bank"], books["loan"], "300", books["sip"])  # said SIP on purpose
    client.patch(f"/api/accounts/{books['loan']['aid']}", json={"payment_category_id": None})
    assert line(budget(client), "SIP")["activity"] == "300.00"


def test_a_category_with_no_plan_and_no_entries_is_in_the_budget(client, books):
    assert {ln["name"] for ln in budget(client)["lines"]} == {"EMI", "SIP"}


def test_an_earning_category_is_never_a_budget_line(client, books, root_accounts):
    account(client, root_accounts, "Salary", "Income")
    assert "Salary" not in {ln["name"] for ln in budget(client)["lines"]}
    refused = client.put(f"/api/budget/categories/{root_accounts['Income']}", json={"amount": "5"})
    assert refused.status_code in (400, 404)
