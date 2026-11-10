"""Paying a loan that is outside the budget: an EMI labelled with a category spends it; one without a label does not.
Nothing is filled in for the person: the label is whatever the line was given."""

import pytest

from app.services import account as account_service

from .books import leg, post_account
from .test_budget import account, assign, budget, line, move


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    loan = account(client, root_accounts, "Home Loan", "Liabilities", on_budget=False)
    emi = account(client, root_accounts, "EMI", "Expenses")
    interest = account(client, root_accounts, "Interest", "Expenses")
    return {"bank": bank, "loan": loan, "emi": emi, "interest": interest}


def test_without_a_category_the_emi_just_lowers_ready_to_assign(client, books):
    assign(client, books["emi"], "15000")
    move(client, books["bank"], books["loan"], "15000")  # EMI: debits the loan, credits the bank
    data = budget(client)
    assert line(data, "EMI")["activity"] == "0.00" and line(data, "EMI")["available"] == "15000.00"
    assert data["ready_to_assign"] == "70000.00", "the EMI left the bank and the envelope still holds 15000"


def test_with_a_category_the_emi_spends_it(client, books):
    assign(client, books["emi"], "15000")
    move(client, books["bank"], books["loan"], "15000", category=books["emi"])
    data = budget(client)
    emi = line(data, "EMI")
    assert emi["activity"] == "15000.00" and emi["available"] == "0.00"
    assert data["ready_to_assign"] == "85000.00", "assigned and spent: nothing else changes"


def test_a_loan_has_no_usual_category_to_fill_in(client, books):
    loan = client.get(f"/api/accounts/{books['loan']['id']}").json()
    assert "payment_category_id" not in loan
    move(client, books["bank"], books["loan"], "100")
    made = client.get("/api/transactions/").json()[0]
    assert {p["category_id"] for p in made["postings"]} == {None}, "the payment stays without a label"
    assert (
        client.patch(f"/api/accounts/{books['loan']['id']}", json={"payment_category_id": books["emi"]["id"]}).json()[
            "name"
        ]
        == "Home Loan"
    ), "an old client sending the removed field is ignored, not an error"
    assert {p["category_id"] for p in client.get("/api/transactions/").json()[0]["postings"]} == {None}


def test_interest_the_lender_charges_is_not_budget_spending(client, books):
    move(client, books["loan"], books["interest"], "900")  # the lender charges interest to the loan
    assert line(budget(client), "Interest")["activity"] == "0.00"


def test_interest_charged_to_a_loan_in_the_loans_group_makes_no_nudge(monkeypatch, client):
    """A loan under the built-in Loans group (or anything under Investments) is outside the budget by design: no nudge to
    add it, however often it is charged. A card outside the budget is offered."""
    monkeypatch.setattr(account_service, "NEW_PROFILE_FIXED_PARENTS", True)
    listed = client.get("/api/accounts/").json()
    by_key = {a["system_key"]: a["id"] for a in listed if a["system_key"]}
    expenses = next(a["id"] for a in listed if a["name"] == "Expenses" and a["parent_id"] is None)
    car = post_account(client, {"name": "Car loan", "parent_id": by_key["liabilities.loans"]}).json()
    card = post_account(
        client, {"name": "Old card", "parent_id": by_key["liabilities.cards"], "on_budget": False}
    ).json()
    fees = post_account(client, {"name": "Fees", "parent_id": expenses}).json()
    for payer in (car, card):
        client.post(
            "/api/transactions/",
            json={"postings": [leg(fees, "debit", "50"), leg(payer, "credit", "50")]},
        )
    assert [a["path"].split(":")[-1] for a in budget(client)["left_out_accounts"]] == ["Old card"]


def test_borrowing_into_the_bank_is_not_spending(client, books):
    move(
        client, books["loan"], books["bank"], "50000", category=None
    )  # the loan pays out: credit the loan, debit the bank
    data = budget(client)
    assert line(data, "EMI")["activity"] == "0.00" and data["ready_to_assign"] == "150000.00"


def test_a_split_emi_counts_both_parts(client, books):
    client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(books["loan"], "debit", "8000", category_id=books["emi"]["id"]),
                leg(books["interest"], "debit", "2000"),
                leg(books["bank"], "credit", "10000"),
            ]
        },
    )
    data = budget(client)
    assert line(data, "EMI")["activity"] == "8000.00" and line(data, "Interest")["activity"] == "2000.00"
    assert data["cash"] == "90000.00" and data["available"] == "-10000.00", (
        "overspent in its own month: Ready to Assign changes next month"
    )


def test_the_edit_page_has_no_usual_category(client, books):
    page = client.get(f"/accounts/{books['loan']['id']}/edit").text
    assert "Usual category" not in page and 'name="payment_category"' not in page and "Part of the budget" in page
    saved = client.post(
        f"/accounts/{books['loan']['id']}/edit",
        data={"name": "Home Loan", "budget_choice": "1", "payment_category": books["emi"]["id"]},
    )
    assert saved.status_code == 200 and saved.headers["HX-Redirect"].startswith("/accounts/")


# ---- the Categories page sees them too ---------------------------------------------------------------------------------


def test_the_categories_page_and_the_category_page_count_payments_into_the_loan(client, books):
    move(client, books["bank"], books["loan"], "15000", category=books["emi"])
    move(
        client, books["loan"], books["interest"], "900"
    )  # interest charged by the lender: spending on Interest, not a payment
    page = client.get("/categories").text
    assert "15,000.00" in page and "15,900.00" in page, "EMI 15,000 and Interest 900 make 15,900"
    emi = client.get(f"/categories/{books['emi']['id']}").text
    assert "15,000.00" in emi and emi.count('class="tx"') == 1, "the payment is listed under the category"
    assert "Home Loan" in emi


def test_payments_into_a_loan_count_in_a_group_of_categories(client, books, root_accounts):
    debts = account(client, root_accounts, "Debts", "Expenses")
    sub = post_account(client, {"name": "Car EMI", "parent_id": debts["id"]}).json()
    move(client, books["bank"], books["loan"], "7000", category=sub)
    assert "7,000.00" in client.get("/categories").text
    assert "7,000.00" in client.get(f"/categories/{debts['id']}").text, "the group's figure"
    assert client.get(f"/categories/{sub['id']}").text.count('class="tx"') == 1, "listed on the category itself"


def test_every_report_speaks_the_same_language_about_what_an_emi_spent(client, books, svc):
    """The Categories page, the breakdown by category and the overview's `spent` count the EMI once, as spending in the
    category it was labelled with, and the interest the lender charges as the spending it is; borrowing is not spending.
    The books' own view (`expenses`, the breakdown by account) has only the interest: paying into a loan is no expense.
    (The Budget counts only what budget money paid, so interest, which no budget account paid, is not in it.)"""
    assign(client, books["emi"], "15000")
    move(client, books["bank"], books["loan"], "15000", category=books["emi"])  # the EMI
    move(client, books["loan"], books["interest"], "900")  # interest the lender charges
    move(client, books["loan"], books["bank"], "5000")  # borrowing more: not spending

    data = budget(client)
    assert line(data, "EMI")["activity"] == "15000.00" and line(data, "Interest")["activity"] == "0.00"
    summary = svc.reports.summary()
    breakdown = svc.reports.breakdown("Expenses")
    assert str(summary.spent) == "15900.00", "what the budget calls spending"
    assert str(summary.expenses) == "900.00" and str(summary.net_income) == "-900.00", "the books: only the interest"
    assert str(breakdown.total) == "15900.00" and [l.account for l in breakdown.lines] == ["EMI", "Interest"]
    categories = " ".join(client.get("/categories").text.split())
    assert "15,000.00" in categories and "900.00" in categories


def test_without_a_label_no_report_counts_the_emi(client, books, svc):
    move(client, books["bank"], books["loan"], "15000")
    assert str(svc.reports.summary().expenses) == "0.00" and str(svc.reports.summary().spent) == "0.00"
    assert str(svc.reports.breakdown("Expenses").total) == "0.00"
