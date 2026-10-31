"""The budget reads categories: what a line says it was for is what the budget counts, whatever kind of account the
line is on, and a loan's payment category keeps its lines in step."""

import pytest

from .books import leg
from .test_budget import account, assign, budget, line


def paid(client, bank, to, amount, category=None):
    posting = leg(to, "debit", amount)
    if category:
        posting["category_id"] = category["id"]
    response = client.post(
        "/api/transactions/",
        json={"postings": [posting, leg(bank, "credit", amount)]},
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
    client.patch(f"/api/accounts/{books['loan']['id']}", json={"payment_category_id": books["emi"]["id"]})
    assert line(budget(client), "EMI")["activity"] == "700.00"
    client.patch(f"/api/accounts/{books['loan']['id']}", json={"payment_category_id": books["sip"]["id"]})
    data = budget(client)
    assert (line(data, "EMI")["activity"], line(data, "SIP")["activity"]) == ("0.00", "700.00")
    client.patch(f"/api/accounts/{books['loan']['id']}", json={"payment_category_id": None})
    assert line(budget(client), "SIP")["activity"] == "0.00"


def test_a_label_the_person_chose_survives_a_change_of_the_loans_category(client, books):
    client.patch(f"/api/accounts/{books['loan']['id']}", json={"payment_category_id": books["emi"]["id"]})
    paid(client, books["bank"], books["loan"], "300", books["sip"])  # said SIP on purpose
    client.patch(f"/api/accounts/{books['loan']['id']}", json={"payment_category_id": None})
    assert line(budget(client), "SIP")["activity"] == "300.00"


def test_a_category_with_no_plan_and_no_entries_is_in_the_budget(client, books):
    assert {ln["name"] for ln in budget(client)["lines"]} == {"EMI", "SIP"}


def test_an_earning_category_is_never_a_budget_line(client, books, root_accounts):
    account(client, root_accounts, "Salary", "Income")
    assert "Salary" not in {ln["name"] for ln in budget(client)["lines"]}
    refused = client.put(f"/api/budget/categories/{root_accounts['Income']}", json={"amount": "5"})
    assert refused.status_code in (400, 404)


# ---- payments with no category -----------------------------------------------------------------


def test_a_payment_into_a_loan_with_no_category_is_listed_until_it_gets_one(client, books):
    made = paid(client, books["bank"], books["loan"], "19277")
    listed = budget(client)["uncategorised"]
    assert [(u["transaction_id"], u["amount"], u["account"]) for u in listed] == [
        (made["id"], "19277.00", "Liabilities:Home Loan")
    ]
    assert "needs you" not in client.get("/budget").text, "what needs a decision lives under the bell"
    todo = client.get("/api/todo/").json()
    assert todo["count"] == 1 and [u["transaction_id"] for u in todo["uncategorised"]] == [made["id"]]
    assert "1 payment has no category" in client.get("/todo/sheet").text
    answer = client.post(f"/todo/payments/{made['id']}/category", data={"category": books["emi"]["id"]})
    assert answer.status_code == 200
    assert "Nothing needs you" in answer.text
    data = budget(client)
    assert data["uncategorised"] == [] and line(data, "EMI")["activity"] == "19277.00"
    entry = client.get(f"/api/transactions/{made['id']}").json()
    assert {p["category_id"] for p in entry["postings"]} == {None, books["emi"]["id"]}


def test_payments_that_have_a_category_or_stay_inside_the_budget_are_not_listed(client, books, root_accounts):
    paid(client, books["bank"], books["loan"], "100", books["emi"])
    paid(client, books["bank"], books["sip"], "5")  # an expense account: its own category
    cash = account(client, root_accounts, "Cash", "Assets")
    paid(client, books["bank"], cash, "50")  # a move inside the budget
    assert budget(client)["uncategorised"] == []
    assert "no category" not in client.get("/todo/sheet").text


def test_giving_a_payment_a_category_is_refused_for_what_does_not_wait_for_one(client, books):
    made = paid(client, books["bank"], books["loan"], "100", books["emi"])
    refused = client.post(f"/todo/payments/{made['id']}/category", data={"category": books["sip"]["id"]})
    assert refused.status_code == 400 and "no payment waiting" in refused.text
    missing = client.post(
        "/todo/payments/00000000-0000-4000-8000-0000000000aa/category", data={"category": books["sip"]["id"]}
    )
    assert missing.status_code == 404
