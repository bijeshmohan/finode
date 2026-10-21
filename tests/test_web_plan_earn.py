"""The Earn chip: shown only with Advanced on, the month in one line, rows and their sheet."""

from datetime import date

from .test_budget import account, assign, budget, move
from .test_plan_earn import books  # noqa: F401  (the fixture)

THIS_KEY = date.today().strftime("%Y-%m")


def page(client, tab=""):
    return client.get(f"/plan{'?tab=' + tab if tab else ''}").text


def advanced(client, on: bool):
    assert client.patch("/api/profile/", json={"advanced": on}).status_code == 200


def test_the_earn_chip_is_there_only_with_advanced_on(client, books):
    text = page(client)
    assert ">Earn<" in text and "&tab=earn" in text
    advanced(client, False)
    off = page(client)
    assert ">Earn<" not in off and ">Build<" in off, "Build stays: it is not an advanced feature"
    asked = page(client, "earn")
    assert "data-budget-earning" not in asked and "data-budget-tree" in asked, "no Earn without Advanced: Spend shows"


def test_the_earn_list_shows_expected_and_received_with_the_month_in_one_line(client, books):
    assign(client, books["salary"], "85000")
    move(client, books["salary"], books["bank"], "85000")
    assign(client, books["food"], "9000")
    text = " ".join(page(client, "earn").split())
    assert 'aria-pressed="true">Earn<' in text and "data-budget-earning" in text and "data-budget-tree" not in text
    assert "Salary" in text and "received 85,000.00" in text and "85,000.00" in text and "Interest" in text and "nothing received yet" in text
    assert "The month in one line" in text and "Expected" in text and "Unplanned" in text
    assert "<b>76,000</b>" in page(client, "earn").replace("\n", "").replace("  ", ""), "85,000 expected - 0 saving - 9,000 spending"
    assert "Received so far: ₹85,000.00" in text


def test_when_more_is_planned_than_expected_it_says_over_planned(client, books):
    assign(client, books["salary"], "1000")
    assign(client, books["food"], "4000")
    text = " ".join(page(client, "earn").split())
    assert "Over-planned" in text and "3,000" in text


def test_the_sheet_sets_what_is_expected_and_stays_on_earn(client, books):
    sheet = client.get(f"/plan/category/{books['salary']['aid']}/sheet").text
    assert "Expected this month" in sheet and "Received so far" in sheet and "Still to come" in sheet
    assert 'name="tab" value="earn"' in sheet and "Move money" not in sheet and "Ready to assign" in sheet
    answered = client.post("/plan/assign", data={"category": books["salary"]["aid"], "amount": "5000", "sheet": "1", "tab": "earn"})
    assert answered.status_code == 200 and "data-budget-earning" in answered.text
    assert next(l for l in budget(client)["earning"] if l["name"] == "Salary")["expected"] == "5000.00"
    advanced(client, False)
    assert client.get(f"/plan/category/{books['salary']['aid']}/sheet").status_code == 404, "Earn is Advanced only"


def test_without_income_accounts_the_tab_invites_one(client, root_accounts):
    account(client, root_accounts, "Bank", "Assets", balance="10")
    text = page(client, "earn")
    assert "no income accounts yet" in text.lower() and "/categories/new?root=income" in text
