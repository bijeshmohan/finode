"""Going past the plan: red in Spend (overspent), green in Build (more moved or paid than planned)."""

from datetime import date

from .test_budget import account, assign, move


def month() -> str:
    return date.today().strftime("%Y-%m")


def setup(client, root):
    bank = account(client, root, "Bank", "Assets", balance="100000")
    fund = account(client, root, "Mutual Funds", "Assets", on_budget=False, saving=True)
    food = account(client, root, "Food", "Expenses")
    return bank, fund, food


def test_build_past_its_plan_is_green_and_says_above_plan(client, root_accounts):
    bank, fund, _ = setup(client, root_accounts)
    assign(client, fund, "5000")
    move(client, bank, fund, "8000")
    text = client.get(f"/plan?month={month()}&tab=build").text
    assert 'class="bar above"' in text and 'class="bar over"' not in text
    assert "above plan" in text
    sheet = client.get(f"/plan/category/{fund['aid']}/sheet?month={month()}").text
    assert 'sheet-amount income' in sheet and "above plan" in sheet


def test_spend_past_its_budget_stays_red(client, root_accounts):
    bank, _, food = setup(client, root_accounts)
    assign(client, food, "1000")
    move(client, bank, food, "1500")
    text = client.get(f"/plan?month={month()}").text
    assert 'class="bar over"' in text and 'class="bar above"' not in text and "above plan" not in text


def test_being_above_plan_in_build_raises_no_overspent_warning(client, root_accounts):
    bank, fund, _ = setup(client, root_accounts)
    assign(client, fund, "5000")
    move(client, bank, fund, "8000")
    assert "Overspent by" not in client.get(f"/plan?month={month()}").text
    assert "overspent" not in client.get("/").text


def test_the_overspent_box_belongs_to_spend_and_stays_off_the_build_chip(client, root_accounts):
    bank, fund, food = setup(client, root_accounts)
    assign(client, food, "1000")
    move(client, bank, food, "1500")
    assert "Overspent by" in client.get(f"/plan?month={month()}").text
    assert "Overspent by" not in client.get(f"/plan?month={month()}&tab=build").text
