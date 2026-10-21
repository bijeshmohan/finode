"""Plan > Build with groups: the accounts of a group (Investments) are one row, which opens the group's page."""

from decimal import Decimal

import pytest

from .test_budget import account, assign, budget, identity, move
from .test_web_plan_save import page


@pytest.fixture
def books(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="100000")
    inv = account(client, root_accounts, "Investments", "Assets", on_budget=False)
    fund = client.post("/api/accounts/", json={"name": "Mutual Funds", "parent_id": inv["aid"], "on_budget": False, "saving": True}).json()
    ppf = client.post("/api/accounts/", json={"name": "PPF", "parent_id": inv["aid"], "on_budget": False, "saving": True}).json()
    gold = client.post("/api/accounts/", json={"name": "Gold ETF", "parent_id": inv["aid"], "on_budget": False}).json()
    loans = account(client, root_accounts, "Loans", "Liabilities", on_budget=False)
    home = client.post("/api/accounts/", json={"name": "Home Loan", "parent_id": loans["aid"], "on_budget": False, "saving": True, "balance": "1000000"}).json()
    cash = account(client, root_accounts, "Gold fund", "Assets", on_budget=False, saving=True)
    return {"bank": bank, "inv": inv, "fund": fund, "ppf": ppf, "gold": gold, "loans": loans, "home": home, "cash": cash}


def test_the_accounts_of_a_group_are_one_row_with_the_sum(client, books):
    assign(client, books["fund"], "10000")
    assign(client, books["ppf"], "5000")
    assign(client, books["home"], "8000")
    assign(client, books["cash"], "2000")
    text = " ".join(page(client, "build").split())
    assert "data-budget-saving" in text and f'/plan/group/{books["inv"]["aid"]}' in text and f'/plan/group/{books["loans"]["aid"]}' in text
    assert "Investments" in text and "Mutual Funds · PPF" in text and "15,000.00" in text, "the group's row: names inside, the total"
    assert 'href="/plan/target?month=' in text, "the plain account is still a row of its own"
    assert text.index("Investments") < text.index("Loans") < text.index("Gold fund") or text.index("Investments") < text.index("Gold fund"), "biggest plan first"
    assert f'hx-get="/plan/category/{books["fund"]["aid"]}/sheet' not in text, "the group's accounts are on its page"


def test_the_group_page_ranks_its_accounts_and_names_the_ones_left_out(client, books):
    assign(client, books["fund"], "10000")
    assign(client, books["ppf"], "5000")
    move(client, books["bank"], books["fund"], "4000")
    text = " ".join(client.get(f"/plan/group/{books['inv']['aid']}").text.split())
    assert "Investments" in text and "Moved 4,000.00 of 15,000.00" in text and "11,000.00" in text
    assert text.index("Mutual Funds") < text.index("PPF")
    assert f'hx-get="/plan/category/{books["fund"]["aid"]}/sheet' in text and f"group={books['inv']['aid']}" in text
    assert "Not in Build here" in text and "Gold ETF" in text
    assert "hx-get=\"/plan/group/" not in text, "its figure is read-only: no sheet for the group itself"
    assert 'href="/plan?month=' in text and "&amp;tab=build" in text, "back goes to the Build chip"


def test_a_loan_group_says_paid_down_and_still_owed(client, books):
    assign(client, books["home"], "8000")
    move(client, books["bank"], books["home"], "8000")
    text = " ".join(client.get(f"/plan/group/{books['loans']['aid']}").text.split())
    assert "Paid down 8,000.00 of 8,000.00" in text and "still owed" in text and "Not in Build here" not in text
    listing = " ".join(page(client, "build").split())
    assert "paid 8,000 · Home Loan" in listing


def test_assigning_from_a_group_page_comes_back_to_that_page(client, books):
    sheet = client.get(f"/plan/category/{books['fund']['aid']}/sheet?group={books['inv']['aid']}").text
    assert 'name="group"' in sheet and 'name="tab" value="build"' in sheet
    answered = client.post("/plan/assign", data={"category": books["fund"]["aid"], "amount": "700", "sheet": "1", "tab": "build", "group": books["inv"]["aid"]})
    assert answered.status_code == 200 and "Mutual Funds" in answered.text and "700.00" in answered.text
    assert budget(client)["ready_to_assign"] == "99300.00"


def test_a_group_has_no_budget_of_its_own_and_the_arithmetic_is_unchanged(client, books):
    assert client.get(f"/plan/group/{books['inv']['aid']}/sheet").status_code == 404
    assert client.post(f"/plan/group/{books['inv']['aid']}/assign", data={"amount": "5"}).status_code in (400, 404)
    assign(client, books["fund"], "1000")
    assign(client, books["ppf"], "500")
    data = budget(client)
    assert Decimal(data["saving_assigned"]) == Decimal("1500.00")
    identity(data)


def test_a_group_with_nothing_in_build_is_not_a_row(client, books):
    client.patch(f"/api/accounts/{books['fund']['aid']}", json={"saving": False})
    client.patch(f"/api/accounts/{books['ppf']['aid']}", json={"saving": False})
    text = page(client, "build")
    assert f'/plan/group/{books["inv"]["aid"]}' not in text
    assert client.get(f"/plan/group/{books['inv']['aid']}").status_code == 404
