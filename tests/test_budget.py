"""Envelope budgeting on top of the ledger: ready to assign, assigning, moving, carrying over."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

THIS_MONTH = date.today().replace(day=1)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def account(client, root, name, parent, **extra):
    response = client.post("/api/accounts/", json={"name": name, "parent_id": root[parent], **extra})
    assert response.status_code == 201, response.text
    return response.json()


def move(client, source, target, amount, on=None):
    body = {
        "postings": [
            {"account": target["aid"], "side": "debit", "amount": amount},
            {"account": source["aid"], "side": "credit", "amount": amount},
        ]
    }
    if on:
        body["date"] = on
    response = client.post("/api/transactions/", json=body)
    assert response.status_code == 201, response.text


def budget(client, month=None):
    response = client.get("/api/budget/", params={"month": month.isoformat()} if month else {})
    assert response.status_code == 200, response.text
    return response.json()


def assign(client, category, amount, month=None):
    body = {"amount": amount}
    if month:
        body["month"] = month.isoformat()
    response = client.put(f"/api/budget/categories/{category['aid']}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def line(data, name):
    return next(l for l in data["lines"] if l["name"] == name)


@pytest.fixture
def setup(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="1000")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    rent = account(client, root_accounts, "Rent", "Expenses")
    return {"bank": bank, "salary": salary, "food": food, "rent": rent, "roots": root_accounts}


# ---- which accounts count ----------------------------------------------------------------------


def test_new_asset_accounts_holding_a_currency_are_part_of_the_budget(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets")
    coins = account(client, root_accounts, "Coins", "Assets", commodity="BTC")
    card = account(client, root_accounts, "Card", "Liabilities")
    assert bank["on_budget"] is True
    assert coins["on_budget"] is False, "only a currency"
    assert card["on_budget"] is False, "cards are opted in"
    assert account(client, root_accounts, "Other", "Assets", on_budget=False)["on_budget"] is False


def test_the_flag_can_be_changed_but_only_where_it_makes_sense(client, root_accounts):
    card = account(client, root_accounts, "Card", "Liabilities")
    ok = client.patch(f"/api/accounts/{card['aid']}", json={"on_budget": True})
    assert ok.status_code == 200 and ok.json()["on_budget"] is True
    assert client.patch(f"/api/accounts/{card['aid']}", json={"on_budget": False}).json()["on_budget"] is False
    coins = account(client, root_accounts, "Coins", "Assets", commodity="BTC")
    bad = client.patch(f"/api/accounts/{coins['aid']}", json={"on_budget": True})
    assert bad.status_code == 400 and "currency" in bad.json()["detail"]
    food = account(client, root_accounts, "Food", "Expenses")
    assert client.patch(f"/api/accounts/{food['aid']}", json={"on_budget": True}).status_code == 400
    group = account(client, root_accounts, "Banks", "Assets", on_budget=False)
    account_child = client.post("/api/accounts/", json={"name": "Child", "parent_id": group["aid"]}).json()
    assert client.patch(f"/api/accounts/{group['aid']}", json={"on_budget": True}).status_code == 400
    assert account_child["on_budget"] is True


def test_changing_what_an_account_holds_takes_it_out_of_the_budget(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets")
    changed = client.patch(f"/api/accounts/{bank['aid']}", json={"commodity": "BTC"})
    assert changed.status_code == 200 and changed.json()["on_budget"] is False


# ---- ready to assign -----------------------------------------------------------------------------


def test_the_money_in_budget_accounts_is_ready_to_assign(client, setup):
    data = budget(client)
    assert data["ready_to_assign"] == "1000.00" and data["cash"] == "1000.00"
    assert data["budget_accounts"] == ["Assets:Bank"] and data["currency"] == "INR"
    assert {l["name"] for l in data["lines"]} == {"Food", "Rent"}


def test_income_raises_it_and_assigning_lowers_it(client, setup):
    move(client, setup["salary"], setup["bank"], "500")
    assert budget(client)["ready_to_assign"] == "1500.00"
    data = assign(client, setup["food"], "300")
    assert data["ready_to_assign"] == "1200.00" and line(data, "Food")["assigned"] == "300.00"
    assert line(data, "Food")["available"] == "300.00"


def test_setting_an_amount_replaces_it_and_zero_removes_it(client, setup):
    assign(client, setup["food"], "300")
    assert line(assign(client, setup["food"], "100"), "Food")["assigned"] == "100.00"
    data = assign(client, setup["food"], "0")
    assert line(data, "Food")["assigned"] == "0.00" and data["ready_to_assign"] == "1000.00"


def test_spending_lowers_the_category_not_ready_to_assign(client, setup):
    assign(client, setup["food"], "300")
    move(client, setup["bank"], setup["food"], "120")
    data = budget(client)
    food = line(data, "Food")
    assert food["activity"] == "120.00" and food["available"] == "180.00"
    assert data["ready_to_assign"] == "700.00", "1000 - 120 spent - 180 left in Food = 700... and Rent has nothing"


def test_a_refund_gives_money_back_to_the_category(client, setup):
    assign(client, setup["food"], "300")
    move(client, setup["bank"], setup["food"], "120")
    move(client, setup["food"], setup["bank"], "20")
    assert line(budget(client), "Food")["available"] == "200.00"


def test_unassigned_spending_overspends_the_category(client, setup):
    move(client, setup["bank"], setup["rent"], "50")
    data = budget(client)
    assert line(data, "Rent")["available"] == "-50.00"
    assert data["ready_to_assign"] == "1000.00", "cash fell by 50 and so did what is available"


def test_transfers_between_budget_accounts_change_nothing(client, root_accounts, setup):
    other = account(client, root_accounts, "Savings", "Assets")
    move(client, setup["bank"], other, "400")
    assert budget(client)["ready_to_assign"] == "1000.00"


def test_money_moved_out_of_the_budget_lowers_ready_to_assign(client, root_accounts, setup):
    vault = account(client, root_accounts, "Vault", "Assets", on_budget=False)
    move(client, setup["bank"], vault, "400")
    data = budget(client)
    assert data["ready_to_assign"] == "600.00" and data["budget_accounts"] == ["Assets:Bank"]


def test_spending_from_outside_the_budget_is_not_the_budgets_business(client, root_accounts, setup):
    vault = account(client, root_accounts, "Vault", "Assets", on_budget=False, balance="200")
    move(client, vault, setup["food"], "80")
    data = budget(client)
    assert line(data, "Food")["activity"] == "0.00" and data["ready_to_assign"] == "1000.00"


# ---- credit cards ----------------------------------------------------------------------------------


def test_a_card_in_the_budget_makes_purchases_count_and_payments_neutral(client, root_accounts, setup):
    card = account(client, root_accounts, "Card", "Liabilities", on_budget=True)
    assign(client, setup["food"], "300")
    move(client, card, setup["food"], "100")  # bought on the card
    data = budget(client)
    assert line(data, "Food")["available"] == "200.00"
    assert data["cash"] == "900.00", "the card's debt counts against the cash"
    assert data["ready_to_assign"] == "700.00"
    move(client, setup["bank"], card, "100")  # paid the card off
    data = budget(client)
    assert data["cash"] == "900.00" and data["ready_to_assign"] == "700.00"
    assert "Liabilities:Card" in data["budget_accounts"]


def test_a_card_left_out_of_the_budget_is_ignored(client, root_accounts, setup):
    card = account(client, root_accounts, "Card", "Liabilities")
    move(client, card, setup["food"], "100")
    assert line(budget(client), "Food")["activity"] == "0.00"


# ---- months ------------------------------------------------------------------------------------------


def test_what_is_left_carries_into_the_next_month(client, setup):
    assign(client, setup["food"], "300", LAST_MONTH)
    move(client, setup["bank"], setup["food"], "100", on=LAST_MONTH.replace(day=15).isoformat())
    last = budget(client, LAST_MONTH)
    assert line(last, "Food")["available"] == "200.00"
    this = budget(client, THIS_MONTH)
    food = line(this, "Food")
    assert food["assigned"] == "0.00" and food["activity"] == "0.00" and food["available"] == "200.00"
    assert this["ready_to_assign"] == "700.00"
    assert last["ready_to_assign"] == "-300.00", "last month the 1000 did not exist yet (it arrived today)"


def test_an_overspent_category_starts_the_next_month_at_zero(client, setup):
    assign(client, setup["rent"], "10", LAST_MONTH)  # budgeting started last month
    move(client, setup["bank"], setup["rent"], "40", on=LAST_MONTH.replace(day=10).isoformat())
    this = budget(client, THIS_MONTH)
    rent = line(this, "Rent")
    assert rent["available"] == "0.00" and rent["overspent_last_month"] == "30.00"
    assert this["overspent_last_month"] == "30.00"


def test_a_month_shows_the_state_at_its_end(client, setup):
    move(client, setup["salary"], setup["bank"], "500", on=THIS_MONTH.replace(day=2).isoformat())
    assert budget(client, LAST_MONTH)["ready_to_assign"] == "0.00", "the opening balance arrived this month"
    assert budget(client, THIS_MONTH)["ready_to_assign"] == "1500.00"


def test_any_day_in_the_month_names_it(client, setup):
    day = THIS_MONTH.replace(day=17)
    assign(client, setup["food"], "50", day)
    assert budget(client, THIS_MONTH)["month"] == THIS_MONTH.isoformat()
    assert line(budget(client, THIS_MONTH), "Food")["assigned"] == "50.00"


# ---- groups --------------------------------------------------------------------------------------------


def test_sub_categories_roll_up_into_their_group(client, root_accounts, setup):
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": setup["food"]["aid"]}).json()
    dining = client.post("/api/accounts/", json={"name": "Dining", "parent_id": setup["food"]["aid"]}).json()
    assign(client, groceries, "200")
    assign(client, dining, "100")
    move(client, setup["bank"], groceries, "50")
    data = budget(client)
    names = [l["name"] for l in data["lines"]]
    assert names == ["Food", "Dining", "Groceries", "Rent"]
    food = line(data, "Food")
    assert food["group"] and food["assigned"] == "300.00" and food["activity"] == "50.00" and food["available"] == "250.00"
    assert not line(data, "Groceries")["group"]
    assert data["available"] == "250.00" and data["ready_to_assign"] == "700.00"


def test_a_group_posted_to_directly_gets_its_own_row(client, root_accounts, setup):
    client.post("/api/accounts/", json={"name": "Groceries", "parent_id": setup["food"]["aid"]})
    move(client, setup["bank"], setup["food"], "30")
    data = budget(client)
    other = line(data, "Food (other)")
    assert other["activity"] == "30.00" and other["aid"] == setup["food"]["aid"] and other["depth"] == 2
    assert line(data, "Food")["activity"] == "30.00"


# ---- moving money --------------------------------------------------------------------------------------


def test_money_moves_between_categories(client, setup):
    assign(client, setup["food"], "300")
    response = client.post(
        "/api/budget/move",
        json={"from_category": setup["food"]["aid"], "to_category": setup["rent"]["aid"], "amount": "120"},
    )
    assert response.status_code == 200
    data = response.json()
    assert line(data, "Food")["available"] == "180.00" and line(data, "Rent")["available"] == "120.00"
    assert data["ready_to_assign"] == "700.00", "moving does not change what is left to assign"


def test_only_what_is_available_can_be_moved(client, setup):
    assign(client, setup["food"], "100")
    response = client.post(
        "/api/budget/move",
        json={"from_category": setup["food"]["aid"], "to_category": setup["rent"]["aid"], "amount": "150"},
    )
    assert response.status_code == 400 and "only 100.00 is available" in response.json()["detail"]
    same = client.post(
        "/api/budget/move",
        json={"from_category": setup["food"]["aid"], "to_category": setup["food"]["aid"], "amount": "1"},
    )
    assert same.status_code == 400 and "different" in same.json()["detail"]
    assert client.post(
        "/api/budget/move",
        json={"from_category": setup["food"]["aid"], "to_category": setup["rent"]["aid"], "amount": "0"},
    ).status_code == 422


# ---- guards ----------------------------------------------------------------------------------------------


def test_only_expense_accounts_are_categories(client, setup):
    response = client.put(f"/api/budget/categories/{setup['bank']['aid']}", json={"amount": "5"})
    assert response.status_code == 400 and "expense" in response.json()["detail"]
    assert client.put(
        "/api/budget/categories/00000000-0000-4000-8000-0000000000aa", json={"amount": "5"}
    ).status_code == 400


def test_amounts_follow_the_currencys_decimals(client, setup):
    response = client.put(f"/api/budget/categories/{setup['food']['aid']}", json={"amount": "1.234"})
    assert response.status_code == 400 and "decimal" in response.json()["detail"]


def test_deleting_a_category_removes_its_plan(client, setup):
    assign(client, setup["rent"], "100")
    assert client.delete(f"/api/accounts/{setup['rent']['aid']}").status_code == 204
    data = budget(client)
    assert data["ready_to_assign"] == "1000.00" and {l["name"] for l in data["lines"]} == {"Food"}


def test_the_budget_does_not_touch_the_ledger(client, setup):
    before = client.get("/api/reports/trial-balance").json()
    assign(client, setup["food"], "300")
    assert client.get("/api/reports/trial-balance").json() == before


def test_an_account_in_another_currency_is_left_out_and_said_so(client, root_accounts, setup):
    usd = account(client, root_accounts, "Dollars", "Assets", commodity="USD")
    assert usd["on_budget"] is True
    data = budget(client)
    assert data["budget_accounts"] == ["Assets:Bank"] and data["ignored_accounts"] == ["Assets:Dollars"]


def usd_purchase(client, setup):
    """Bought food for 2 USD with INR from the bank: the transaction is in USD, the accounts in INR."""
    response = client.post(
        "/api/transactions/",
        json={
            "currency": "USD",
            "postings": [
                {"account": setup["food"]["aid"], "side": "debit", "amount": "160", "value": "2"},
                {"account": setup["bank"]["aid"], "side": "credit", "amount": "160", "value": "2"},
            ],
        },
    )
    assert response.status_code == 201, response.text


def test_spending_recorded_in_another_currency_is_converted(client, setup):
    client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "price": "80", "date": date.today().isoformat()})
    usd_purchase(client, setup)
    data = budget(client)
    assert line(data, "Food")["activity"] == "160.00" and not data["unpriced"]


def test_the_rate_of_the_transaction_itself_converts_its_spending(client, setup):
    usd_purchase(client, setup)  # 160 INR worth 2 USD implies the rate
    data = budget(client)
    assert line(data, "Food")["activity"] == "160.00" and not data["unpriced"]


def test_the_empty_budget(client, root_accounts):
    data = budget(client)
    assert data["ready_to_assign"] == "0.00" and data["lines"] == [] and data["budget_accounts"] == []


# ---- cash overspending, the YNAB way ---------------------------------------------------------------


@pytest.fixture
def lastmonth(client, root_accounts):
    """1000 arrived last month, nothing assigned yet."""
    bank = account(client, root_accounts, "Bank", "Assets")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    rent = account(client, root_accounts, "Rent", "Expenses")
    move(client, salary, bank, "1000", on=LAST_MONTH.replace(day=2).isoformat())
    assign(client, food, "100", LAST_MONTH)
    move(client, bank, food, "130", on=LAST_MONTH.replace(day=15).isoformat())
    return {"bank": bank, "food": food, "rent": rent, "salary": salary}


def test_overspending_shows_red_in_its_own_month_without_changing_ready_to_assign(client, lastmonth):
    last = budget(client, LAST_MONTH)
    assert line(last, "Food")["available"] == "-30.00"
    assert last["ready_to_assign"] == "900.00", "cash 870, and the deficit is still counted against it"
    assert last["overspent_last_month"] == "0.00"


def test_the_overspending_is_taken_out_of_ready_to_assign_the_next_month(client, lastmonth):
    this = budget(client, THIS_MONTH)
    assert this["cash"] == "870.00"
    assert line(this, "Food")["available"] == "0.00" and line(this, "Food")["overspent_last_month"] == "30.00"
    assert this["ready_to_assign"] == "870.00", "the 30 that was overspent has left the budget for good"
    assert this["overspent_last_month"] == "30.00"


def test_covering_it_means_assigning_the_next_month_from_zero(client, lastmonth):
    data = assign(client, lastmonth["food"], "50", THIS_MONTH)
    assert line(data, "Food")["available"] == "50.00", "not 20: the deficit does not come back"
    assert data["ready_to_assign"] == "820.00"


def test_only_the_month_after_the_overspending_deducts_it(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    two_ago = (LAST_MONTH - timedelta(days=1)).replace(day=1)
    move(client, salary, bank, "1000", on=two_ago.replace(day=2).isoformat())
    assign(client, food, "10", two_ago)
    move(client, bank, food, "40", on=two_ago.replace(day=10).isoformat())
    last = budget(client, LAST_MONTH)
    assert line(last, "Food")["available"] == "0.00" and last["overspent_last_month"] == "30.00"
    assert last["ready_to_assign"] == "960.00"
    this = budget(client, THIS_MONTH)
    assert this["overspent_last_month"] == "0.00" and this["ready_to_assign"] == "960.00", "deducted once, not every month"


def test_money_assigned_later_in_the_month_can_still_cover_a_deficit(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    move(client, salary, bank, "1000", on=LAST_MONTH.replace(day=2).isoformat())
    move(client, bank, food, "60", on=LAST_MONTH.replace(day=5).isoformat())  # overspent mid-month
    assign(client, food, "100", LAST_MONTH)  # ...then covered before the month ended
    last = budget(client, LAST_MONTH)
    assert line(last, "Food")["available"] == "40.00" and last["overspent_last_month"] == "0.00"
    assert line(budget(client, THIS_MONTH), "Food")["available"] == "40.00"


def test_groups_add_up_the_overspending_of_their_categories(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets")
    salary = account(client, root_accounts, "Salary", "Income")
    food = account(client, root_accounts, "Food", "Expenses")
    groceries = client.post("/api/accounts/", json={"name": "Groceries", "parent_id": food["aid"]}).json()
    dining = client.post("/api/accounts/", json={"name": "Dining", "parent_id": food["aid"]}).json()
    move(client, salary, bank, "1000", on=LAST_MONTH.replace(day=2).isoformat())
    assign(client, groceries, "10", LAST_MONTH)
    move(client, bank, groceries, "30", on=LAST_MONTH.replace(day=5).isoformat())
    move(client, bank, dining, "20", on=LAST_MONTH.replace(day=6).isoformat())
    data = budget(client, THIS_MONTH)
    assert line(data, "Food")["overspent_last_month"] == "40.00" and data["overspent_last_month"] == "40.00"
    assert data["ready_to_assign"] == "950.00"


def test_a_category_with_nothing_available_cannot_give_money_away(client, lastmonth):
    response = client.post(
        "/api/budget/move",
        json={"from_category": lastmonth["food"]["aid"], "to_category": lastmonth["rent"]["aid"],
              "amount": "5", "month": THIS_MONTH.isoformat()},
    )
    assert response.status_code == 400 and "nothing available to move" in response.json()["detail"]


# ---- targets ------------------------------------------------------------------------------------------


def fixture_budget(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="2000")
    food = account(client, root_accounts, "Food", "Expenses")
    rent = account(client, root_accounts, "Rent", "Expenses")
    return bank, food, rent


def target(client, category, kind, amount, **extra):
    response = client.put(f"/api/budget/categories/{category['aid']}/target", json={"kind": kind, "amount": amount, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def line(data, name):
    return next(l for l in data["lines"] if l["name"] == name)


def test_monthly_target_is_underfunded_until_assigned(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    data = target(client, rent, "monthly", "800")
    assert line(data, "Rent")["underfunded"] == "800.00" and data["underfunded"] == "800.00"
    assert line(data, "Rent")["target"]["kind"] == "monthly"
    assign(client, rent, "300")
    data = budget(client)
    assert line(data, "Rent")["underfunded"] == "500.00"
    assign(client, rent, "800")
    data = budget(client)
    assert line(data, "Rent")["underfunded"] == "0.00" and data["underfunded"] == "0.00"
    assert line(data, "Rent")["needed"] == "800.00"


def test_refill_target_counts_what_carried_over(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    assign(client, food, "300", LAST_MONTH)
    target(client, food, "refill", "400")
    this = budget(client)
    assert line(this, "Food")["needed"] == "100.00" and line(this, "Food")["underfunded"] == "100.00"
    assign(client, food, "100")
    assert line(budget(client), "Food")["underfunded"] == "0.00"
    # In the month it started, nothing had carried in yet.
    assert line(budget(client, LAST_MONTH), "Food")["needed"] == "400.00"


def test_by_date_target_saves_evenly_over_the_months_left(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    index = THIS_MONTH.year * 12 + THIS_MONTH.month - 1 + 2
    end = date(index // 12, index % 12 + 1, 1)
    target(client, rent, "by_date", "900", target_date=end.isoformat())  # this month and the next two
    assert line(budget(client), "Rent")["needed"] == "300.00"
    assign(client, rent, "300")
    assert line(budget(client), "Rent")["underfunded"] == "0.00"
    # Next month the 300 has carried in, so 600 remains over two months.
    nxt = (THIS_MONTH + timedelta(days=32)).replace(day=1)
    assert line(budget(client, nxt), "Rent")["needed"] == "300.00"


def test_by_date_in_the_final_month_needs_the_rest(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    target(client, rent, "by_date", "1000", target_date=THIS_MONTH.isoformat())
    assign(client, rent, "250")
    data = budget(client)
    assert line(data, "Rent")["needed"] == "1000.00" and line(data, "Rent")["underfunded"] == "750.00"


def test_target_validation(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    url = f"/api/budget/categories/{rent['aid']}/target"
    assert client.put(url, json={"kind": "weekly", "amount": "5"}).status_code == 400
    assert client.put(url, json={"kind": "monthly", "amount": "0"}).status_code == 422
    assert client.put(url, json={"kind": "by_date", "amount": "5"}).status_code == 400
    past = (LAST_MONTH).isoformat()
    assert client.put(url, json={"kind": "by_date", "amount": "5", "target_date": past}).status_code == 400
    assert client.put(f"/api/budget/categories/{bank['aid']}/target", json={"kind": "monthly", "amount": "5"}).status_code == 400
    assert client.put(url, json={"kind": "monthly", "amount": "5.123"}).status_code == 400


def test_replacing_and_clearing_a_target(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    target(client, rent, "monthly", "800")
    data = target(client, rent, "refill", "500")
    assert line(data, "Rent")["target"]["kind"] == "refill" and line(data, "Rent")["target"]["amount"] == "500.00"
    cleared = client.delete(f"/api/budget/categories/{rent['aid']}/target").json()
    assert line(cleared, "Rent")["target"] is None and cleared["underfunded"] == "0.00"


def test_groups_sum_their_children_underfunded(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    groceries = account(client, root_accounts, "Groceries", "Expenses")
    sub = client.post("/api/accounts/", json={"name": "Dining", "parent_id": food["aid"]}).json()
    client.post("/api/accounts/", json={"name": "Market", "parent_id": food["aid"]})
    market = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Market")
    target(client, sub, "monthly", "100")
    data = target(client, market, "monthly", "50")
    assert line(data, "Food")["underfunded"] == "150.00" and line(data, "Food")["group"] and line(data, "Food")["target"] is None
    assert data["underfunded"] == "150.00"


def test_fund_assigns_what_is_needed_within_ready_to_assign(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)  # 2000 ready to assign
    target(client, rent, "monthly", "1500")
    target(client, food, "monthly", "800")
    response = client.post("/api/budget/fund", json={})
    assert response.status_code == 200, response.text
    data = response.json()
    amounts = {l["name"]: l["assigned"] for l in data["lines"]}
    assert amounts == {"Food": "800.00", "Rent": "1200.00"}, "in display order, until the money runs out"
    assert data["ready_to_assign"] == "0.00" and data["underfunded"] != "0.00"
    assert client.post("/api/budget/fund", json={}).status_code == 400, "nothing left to assign"


def test_fund_with_nothing_underfunded_is_refused(client, root_accounts):
    fixture_budget(client, root_accounts)
    response = client.post("/api/budget/fund", json={})
    assert response.status_code == 400 and "nothing is underfunded" in response.json()["detail"]


def test_deleting_a_category_removes_its_target(client, root_accounts):
    bank, food, rent = fixture_budget(client, root_accounts)
    target(client, rent, "monthly", "800")
    assert client.delete(f"/api/accounts/{rent['aid']}").status_code in (200, 204)
    assert budget(client)["underfunded"] == "0.00"


# ---- first-time setup ------------------------------------------------------------------------------------


def test_history_before_the_first_assignment_is_not_overspending(client, setup):
    move(client, setup["bank"], setup["food"], "40", on=LAST_MONTH.replace(day=10).isoformat())
    data = budget(client, THIS_MONTH)
    assert line(data, "Food")["available"] == "0.00" and data["overspent_last_month"] == "0.00"
    assert data["ready_to_assign"] == "1000.00" or data["ready_to_assign"] == data["cash"], "cash is untouched by the past"


def test_spending_from_a_card_outside_the_budget_is_pointed_out(client, root_accounts):
    bank = account(client, root_accounts, "Bank", "Assets", balance="1000")
    card = account(client, root_accounts, "Card", "Liabilities")
    food = account(client, root_accounts, "Food", "Expenses")
    move(client, card, food, "75")
    data = budget(client)
    assert line(data, "Food")["activity"] == "0.00", "not counted while the card is outside the budget"
    assert data["left_out"] == "75.00"
    assert [(a["path"], a["entries"], a["spent"]) for a in data["left_out_accounts"]] == [("Liabilities:Card", 1, "75.00")]
    client.patch(f"/api/accounts/{card['aid']}", json={"on_budget": True})
    after = budget(client)
    assert line(after, "Food")["activity"] == "75.00" and after["left_out"] == "0.00" and after["left_out_accounts"] == []


def test_spending_paid_from_equity_or_other_currencies_is_not_flagged(client, root_accounts):
    food = account(client, root_accounts, "Food", "Expenses")
    equity = account(client, root_accounts, "Gift", "Equity")
    account(client, root_accounts, "Bank", "Assets", balance="10")
    move(client, equity, food, "5")
    assert budget(client)["left_out"] == "0.00"


# ---- setting up a month quickly ------------------------------------------------------------------------------

NEXT_MONTH = (THIS_MONTH + timedelta(days=32)).replace(day=1)


def test_money_assigned_to_a_later_month_is_out_of_ready_to_assign_now(client, setup):
    before = budget(client)["ready_to_assign"]
    assign(client, setup["food"], "300", NEXT_MONTH)
    now = budget(client)
    assert Decimal(now["ready_to_assign"]) == Decimal(before) - 300
    assert now["assigned_to_later_months"] == "300.00" and line(now, "Food")["assigned"] == "0.00"
    nxt = budget(client, NEXT_MONTH)
    assert nxt["ready_to_assign"] == now["ready_to_assign"], "the same money, seen from the later month"
    assert line(nxt, "Food")["available"] == "300.00" and nxt["assigned_to_later_months"] == "0.00"


def test_later_months_stack_up_and_clear(client, setup):
    assign(client, setup["food"], "100", NEXT_MONTH)
    after = (NEXT_MONTH + timedelta(days=32)).replace(day=1)
    assign(client, setup["rent"], "200", after)
    assert budget(client)["assigned_to_later_months"] == "300.00"
    assign(client, setup["food"], "0", NEXT_MONTH)
    assert budget(client)["assigned_to_later_months"] == "200.00"


def test_copying_last_months_amounts(client, setup):
    assign(client, setup["food"], "300", LAST_MONTH)
    assign(client, setup["rent"], "500", LAST_MONTH)
    assert budget(client)["copyable"] == "800.00"
    response = client.post("/api/budget/copy", json={})
    assert response.status_code == 200
    data = response.json()
    assert line(data, "Food")["assigned"] == "300.00" and line(data, "Rent")["assigned"] == "500.00"
    assert data["copyable"] == "0.00"
    assert client.post("/api/budget/copy", json={}).status_code == 400, "everything is already assigned"


def test_copying_never_overwrites_what_is_assigned(client, setup):
    assign(client, setup["food"], "300", LAST_MONTH)
    assign(client, setup["rent"], "500", LAST_MONTH)
    assign(client, setup["food"], "50")
    assert budget(client)["copyable"] == "500.00"
    data = client.post("/api/budget/copy", json={}).json()
    assert line(data, "Food")["assigned"] == "50.00" and line(data, "Rent")["assigned"] == "500.00"


def test_copying_with_nothing_last_month_is_explained(client, setup):
    response = client.post("/api/budget/copy", json={})
    assert response.status_code == 400 and "nothing assigned to copy" in response.json()["detail"]


def test_copying_into_another_month_uses_the_month_before_it(client, setup):
    assign(client, setup["food"], "70")
    data = client.post("/api/budget/copy", json={"month": NEXT_MONTH.isoformat()}).json()
    assert line(data, "Food")["assigned"] == "70.00" and data["month"] == NEXT_MONTH.isoformat()


def test_copying_skips_closed_categories(client, setup):
    assign(client, setup["food"], "300", LAST_MONTH)
    assign(client, setup["rent"], "500", LAST_MONTH)
    assert client.post(f"/api/accounts/{setup['rent']['aid']}/close").status_code == 200
    data = client.post("/api/budget/copy", json={}).json()
    assert line(data, "Food")["assigned"] == "300.00"
    assert line(data, "Rent")["assigned"] == "0.00", "a closed category gets nothing more (what it holds just carries over)"
