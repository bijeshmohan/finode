"""The Plan's Save section: an asset outside the budget that the person plans to save into (docs/developer/plan-design.md).

A Save line works like a Spend line in arithmetic: what is moved into the account from a budget account is its activity,
so assigning and then moving leaves Ready to assign as it was, and Spend's figures never include it.
"""

from datetime import date

import pytest

from .test_budget import account, assign, budget, identity, move


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    fund = account(client, root_accounts, "Mutual Funds", "Assets", on_budget=False, saving=True)
    food = account(client, root_accounts, "Food", "Expenses")
    return {"bank": bank, "fund": fund, "food": food, "roots": root_accounts}


def saving(data, name="Mutual Funds"):
    return next(l for l in data["saving"] if l["name"] == name)


def test_an_account_planned_for_saving_is_outside_the_budget_and_listed_in_save(client, books):
    fund = client.get(f"/api/accounts/{books['fund']['aid']}").json()
    assert fund["saving"] is True and fund["on_budget"] is False
    data = budget(client)
    assert [l["name"] for l in data["saving"]] == ["Mutual Funds"] and data["lines"] == [{**data["lines"][0]}] and data["lines"][0]["name"] == "Food"
    assert saving(data)["assigned"] == "0.00" and data["left_out_accounts"] == [], "not offered as an account to add to the budget"


def test_assigning_to_a_save_line_takes_the_money_out_of_ready_to_assign(client, books):
    data = assign(client, books["fund"], "15000")
    assert data["ready_to_assign"] == "85000.00" and saving(data)["assigned"] == "15000.00" and saving(data)["available"] == "15000.00"
    assert data["saving_assigned"] == "15000.00" and data["saving_available"] == "15000.00"
    assert data["assigned"] == "0.00" and data["available"] == "0.00", "Spend's figures stay Spend's"
    identity(data)


def test_moving_the_money_in_does_the_job_and_changes_nothing_else(client, books):
    assign(client, books["fund"], "15000")
    move(client, books["bank"], books["fund"], "15000")  # the SIP
    data = budget(client)
    line = saving(data)
    assert line["activity"] == "15000.00" and line["available"] == "0.00" and line["balance"] == "15000.00"
    assert data["ready_to_assign"] == "85000.00", "assigned and moved: nothing else changes"
    assert data["activity"] == "0.00", "saving is not spending"
    identity(data)


def test_without_a_plan_the_money_moved_in_is_activity_and_a_withdrawal_is_not_subtracted(client, books):
    move(client, books["bank"], books["fund"], "4000")
    data = budget(client)
    assert saving(data)["activity"] == "4000.00" and saving(data)["available"] == "-4000.00"
    assert data["ready_to_assign"] == "100000.00", "in its own month an overspent line only shows negative, as a category does"
    identity(data)
    move(client, books["fund"], books["bank"], "1500")  # taking some back
    data = budget(client)
    assert saving(data)["activity"] == "4000.00" and saving(data)["balance"] == "2500.00", "a withdrawal is not subtracted"
    identity(data)


def test_a_target_works_on_a_save_line(client, books):
    response = client.put(f"/api/budget/categories/{books['fund']['aid']}/target", json={"kind": "monthly", "amount": "5000"})
    assert response.status_code == 200, response.text
    data = budget(client)
    assert saving(data)["target"]["kind"] == "monthly" and saving(data)["underfunded"] == "5000.00" and data["underfunded"] == "5000.00"
    funded = client.post("/plan/fund", data={"month": date.today().isoformat()[:7]}, follow_redirects=False)
    assert funded.status_code in (200, 303), funded.text
    data = budget(client)
    assert saving(data)["assigned"] == "5000.00" and saving(data)["underfunded"] == "0.00", "Assign what is needed reaches Save lines too"


def test_money_can_be_moved_between_a_spend_line_and_a_save_line(client, books):
    assign(client, books["food"], "3000")
    response = client.post("/plan/move", data={"from_category": books["food"]["aid"], "to_category": books["fund"]["aid"], "amount": "1000"}, follow_redirects=False)
    assert response.status_code in (200, 303), response.text
    data = budget(client)
    assert saving(data)["assigned"] == "1000.00" and data["lines"][0]["assigned"] == "2000.00" and data["ready_to_assign"] == "97000.00"


def test_it_is_never_spending_in_the_reports(client, books, svc):
    assign(client, books["fund"], "15000")
    move(client, books["bank"], books["fund"], "15000")
    assert str(svc.reports.summary().expenses) == "0.00"
    assert str(svc.reports.breakdown("Expenses").total) == "0.00"


def test_joining_the_budget_takes_it_out_of_save_and_it_cannot_be_both(client, books):
    both = client.patch(f"/api/accounts/{books['fund']['aid']}", json={"on_budget": True, "saving": True})
    assert both.status_code == 400
    assert client.patch(f"/api/accounts/{books['fund']['aid']}", json={"on_budget": True}).status_code == 200
    fund = client.get(f"/api/accounts/{books['fund']['aid']}").json()
    assert fund["on_budget"] is True and fund["saving"] is False
    data = budget(client)
    assert data["saving"] == []
    refused = client.patch(f"/api/accounts/{books['fund']['aid']}", json={"saving": True})
    assert refused.status_code == 400 and "part of the budget" in refused.text


def test_only_an_asset_or_loan_without_sub_accounts_can_be_planned_under_build(client, books):
    cat = account(client, books["roots"], "Rent", "Expenses")
    assert client.patch(f"/api/accounts/{cat['aid']}", json={"saving": True}).status_code == 400, "a category is not an asset or a loan"
    group = account(client, books["roots"], "Investments", "Assets", on_budget=False)
    account(client, books["roots"], "Inner", "Assets")  # an ordinary sibling
    made = client.post("/api/accounts/", json={"name": "Stocks", "parent_id": group["aid"], "on_budget": False})
    assert made.status_code == 201
    assert client.patch(f"/api/accounts/{group['aid']}", json={"saving": True}).status_code == 400, "it has a sub-account"
    assert client.post("/api/accounts/", json={"name": "Bad", "parent_id": books["roots"]["Expenses"], "saving": True}).status_code == 400


def test_switching_saving_on_clears_the_payment_category(client, books):
    emi = account(client, books["roots"], "SIP", "Expenses")
    sip = account(client, books["roots"], "Recurring", "Assets", on_budget=False, payment_category_id=emi["aid"])
    assert sip["payment_category_id"] == emi["aid"]
    updated = client.patch(f"/api/accounts/{sip['aid']}", json={"saving": True})
    assert updated.status_code == 200 and updated.json()["payment_category_id"] is None and updated.json()["saving"] is True
    assert client.patch(f"/api/accounts/{sip['aid']}", json={"payment_category_id": emi["aid"]}).status_code == 400


def test_switching_it_off_keeps_the_amounts_for_when_it_returns(client, books):
    assign(client, books["fund"], "2000")
    client.patch(f"/api/accounts/{books['fund']['aid']}", json={"saving": False})
    data = budget(client)
    assert data["saving"] == [] and data["ready_to_assign"] == "100000.00"
    client.patch(f"/api/accounts/{books['fund']['aid']}", json={"saving": True})
    assert saving(budget(client))["assigned"] == "2000.00"


def test_copying_last_month_includes_save_lines(client, books):
    from datetime import timedelta

    this = date.today().replace(day=1)
    last = (this - timedelta(days=1)).replace(day=1)
    assign(client, books["fund"], "700", month=last)
    copied = client.post("/plan/copy", data={"month": this.isoformat()[:7]}, follow_redirects=False)
    assert copied.status_code in (200, 303), copied.text
    assert saving(budget(client))["assigned"] == "700.00"


def test_the_backup_carries_the_switch(client, books):
    backup = client.get("/api/backup").json()
    assert next(a for a in backup["accounts"] if a["name"] == "Mutual Funds")["saving"] is True
    assert next(a for a in backup["accounts"] if a["name"] == "Bank")["saving"] is False
