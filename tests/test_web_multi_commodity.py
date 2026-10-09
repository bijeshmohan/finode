"""The web UI around accounts and transactions in more than one commodity."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from .htmlutil import element, options, text_of


LONG_AGO = str(date.today() - timedelta(days=60))


def make_account(client, name, parent, commodity=None, **extra):
    body = {"name": name, "parent_id": parent, **extra}
    if commodity:
        body["commodity"] = commodity
    response = client.post("/api/accounts/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def latest(client):
    """The newest transaction dated LONG_AGO (opening balances are dated today)."""
    return next(t for t in client.get("/api/transactions/").json() if t["date"] == LONG_AGO)


@pytest.fixture
def pair(client, root_accounts):
    bank = make_account(client, "HDFC", root_accounts["Assets"], balance="100000.00")
    usd = make_account(client, "Wise USD", root_accounts["Assets"], "USD")
    return bank, usd


def buy_usd_form(bank, usd, **extra):
    return {
        "amount": "8350",
        "to_amount": "100",
        "from_account": bank["aid"],
        "to_account": usd["aid"],
        "date": LONG_AGO,
        **extra,
    }


# ---- account forms ------------------------------------------------------------------------------------------


def test_the_account_form_offers_what_it_holds(client):
    page = client.get("/accounts/new").text
    assert "Holds something other than INR?" in page
    holds = {v: t for v, _, t in options(page[page.index('name="commodity"'):page.index("</select>", page.index('name="commodity"'))])}
    assert holds[""].startswith("Same as where it belongs")
    assert {"USD", "BTC", "EUR"} <= set(holds)
    assert 'name="balance_value"' in page
    assert '<details class="more" >' in page, "collapsed for a plain INR account"


def test_an_account_can_be_added_in_another_commodity(client, root_accounts):
    response = client.post(
        "/accounts",
        data={
            "name": "Wise",
            "parent_id": root_accounts["Assets"],
            "commodity": "USD",
            "balance": "100",
            "balance_value": "8300",
        },
    )
    assert response.status_code == 200 and response.headers["HX-Redirect"].startswith("/accounts/")
    wise = next(a for a in client.get("/api/accounts/").json() if a["name"] == "Wise")
    assert wise["commodity"] == "USD" and wise["balance"] == "100.00"
    assert Decimal(client.get("/api/reports/summary").json()["net_worth"]) == Decimal("8300.00")


def test_a_missing_worth_is_explained_in_the_form(client, root_accounts):
    response = client.post(
        "/accounts",
        data={"name": "Wise", "parent_id": root_accounts["Assets"], "commodity": "USD", "balance": "100"},
    )
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#form-error"
    assert "no USD price is known yet" in response.text
    assert "Wise" not in {a["name"] for a in client.get("/api/accounts/").json()}


def test_an_unknown_commodity_is_explained_in_the_form(client, root_accounts):
    response = client.post(
        "/accounts", data={"name": "X", "parent_id": root_accounts["Assets"], "commodity": "ZZZ"}
    )
    assert response.status_code == 400 and "unknown commodity" in response.text


def test_the_quick_sheet_can_add_a_foreign_account(client, root_accounts):
    sheet = client.get("/accounts/quick").text
    assert 'name="commodity"' in sheet and 'name="balance_value"' in sheet
    response = client.post(
        "/accounts/quick",
        data={"name": "Wise", "parent_id": root_accounts["Assets"], "commodity": "USD", "balance": "10", "balance_value": "830"},
    )
    assert response.status_code == 200 and "account-added" in response.headers["HX-Trigger"]
    assert next(a for a in client.get("/api/accounts/").json() if a["name"] == "Wise")["commodity"] == "USD"


def test_the_edit_form_shows_and_changes_what_an_account_holds(client, root_accounts):
    fresh = make_account(client, "Later", root_accounts["Assets"])
    page = client.get(f"/accounts/{fresh['aid']}/edit").text
    chosen = [v for v, selected, _ in options(page) if selected and v in ("INR", "USD", "EUR")]
    assert chosen == ["INR"]

    response = client.post(f"/accounts/{fresh['aid']}/edit", data={"name": "Later", "parent_id": root_accounts["Assets"], "commodity": "EUR"})
    assert response.status_code == 200
    assert client.get(f"/api/accounts/{fresh['aid']}").json()["commodity"] == "EUR"


def test_what_an_account_holds_is_locked_once_it_has_postings(client, pair, root_accounts):
    bank, usd = pair
    client.post("/transactions", data=buy_usd_form(bank, usd))
    page = client.get(f"/accounts/{usd['aid']}/edit").text
    assert "It has transactions, so what it holds can't change any more." in page
    assert 'name="commodity"' not in page


# ---- the simple transaction form ------------------------------------------------------------------------------




def test_buying_usd_with_inr(client, pair):
    bank, usd = pair
    response = client.post("/transactions", data=buy_usd_form(bank, usd))
    assert response.status_code == 200 and response.headers["HX-Redirect"] == "/transactions"
    txn = latest(client)
    assert txn["currency"] == "INR"
    by_account = {p["account"]: p for p in txn["postings"]}
    assert (by_account[usd["aid"]]["amount"], by_account[usd["aid"]]["value"], by_account[usd["aid"]]["side"]) == ("100.00", "8350.00", "debit")
    assert (by_account[bank["aid"]]["amount"], by_account[bank["aid"]]["value"]) == ("8350.00", "8350.00")


def test_selling_usd_for_inr(client, pair):
    bank, usd = pair
    client.post("/transactions", data=buy_usd_form(bank, usd))
    response = client.post(
        "/transactions",
        data={"amount": "40", "to_amount": "3400", "from_account": usd["aid"], "to_account": bank["aid"], "date": LONG_AGO},
    )
    assert response.status_code == 200
    txn = latest(client)
    values = {p["account"]: (p["amount"], p["value"]) for p in txn["postings"]}
    assert values[usd["aid"]] == ("40.00", "3400.00") and values[bank["aid"]] == ("3400.00", "3400.00")
    assert client.get(f"/api/accounts/{usd['aid']}").json()["balance"] == "60.00"


def test_moving_money_between_two_foreign_currencies_is_in_the_sending_one(client, root_accounts, pair):
    bank, usd = pair
    euro = make_account(client, "Euro pot", root_accounts["Assets"], "EUR")
    client.post("/transactions", data=buy_usd_form(bank, usd))
    response = client.post(
        "/transactions",
        data={"amount": "50", "to_amount": "46", "from_account": usd["aid"], "to_account": euro["aid"], "date": LONG_AGO},
    )
    assert response.status_code == 200, response.text
    txn = latest(client)
    assert txn["currency"] == "USD"
    values = {p["account"]: (p["amount"], p["value"]) for p in txn["postings"]}
    assert values[usd["aid"]] == ("50.00", "50.00") and values[euro["aid"]] == ("46.00", "50.00")


def test_a_transfer_within_one_foreign_commodity_is_in_that_commodity(client, root_accounts, pair):
    bank, usd = pair
    other = make_account(client, "Card USD", root_accounts["Assets"], "USD")
    client.post("/transactions", data=buy_usd_form(bank, usd))
    response = client.post(
        "/transactions",
        data={"amount": "25", "from_account": usd["aid"], "to_account": other["aid"], "date": LONG_AGO},
    )
    assert response.status_code == 200, response.text
    assert latest(client)["currency"] == "USD"
    assert client.get(f"/api/accounts/{other['aid']}").json()["balance"] == "25.00"


def test_the_receive_field_is_needed_between_different_things(client, pair):
    bank, usd = pair
    response = client.post("/transactions", data=buy_usd_form(bank, usd, to_amount=""))
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#form-error"
    assert "say how much USD arrives" in response.text


def test_the_receive_field_must_match_between_the_same_thing(client, root_accounts, account, other_account):
    response = client.post(
        "/transactions",
        data={"amount": "10", "to_amount": "12", "from_account": account["aid"], "to_account": other_account["aid"]},
    )
    assert response.status_code == 400 and "the amount that arrives is the amount that leaves" in response.text
    ok = client.post(
        "/transactions",
        data={"amount": "10", "to_amount": "10.00", "from_account": account["aid"], "to_account": other_account["aid"]},
    )
    assert ok.status_code == 200






# ---- the split form ----------------------------------------------------------------------------------------------


def test_the_split_form_is_unchanged_for_a_single_currency(client, account, expense_account):
    page = client.get("/transactions/new").text
    assert 'name="currency"' not in page and 'name="value"' not in page


def test_the_split_form_asks_for_currency_and_worth_once_something_else_is_held(client, pair):
    page = client.get("/transactions/new").text
    assert 'name="currency"' in page and 'name="value"' in page
    selected = [v for v, s, _ in options(page[page.index('name="currency"'):page.index("</select>", page.index('name="currency"'))]) if s]
    assert selected == ["INR"]
    assert "BTC" not in [v for v, _, _ in options(page[page.index('name="currency"'):page.index("</select>", page.index('name="currency"'))])]
    assert page.count('name="value"') >= 3, "each row, and the one the new-row template clones"


def test_a_split_with_a_worth_for_the_foreign_row(client, pair):
    bank, usd = pair
    response = client.post(
        "/transactions/split",
        data={
            "date": LONG_AGO,
            "currency": "INR",
            "account": [usd["aid"], bank["aid"]],
            "side": ["debit", "credit"],
            "amount": ["100", "8350"],
            "value": ["8350", ""],
        },
    )
    assert response.status_code == 200, response.text
    txn = latest(client)
    assert txn["currency"] == "INR"
    assert {p["account"]: p["value"] for p in txn["postings"]} == {usd["aid"]: "8350.00", bank["aid"]: "8350.00"}


def test_a_split_explains_a_missing_worth(client, pair):
    bank, usd = pair
    response = client.post(
        "/transactions/split",
        data={
            "date": LONG_AGO,
            "currency": "INR",
            "account": [usd["aid"], bank["aid"]],
            "side": ["debit", "credit"],
            "amount": ["100", "8350"],
            "value": ["", ""],
        },
    )
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#form-error"
    assert "must balance" in response.text and "say what that row is worth" in response.text


def test_editing_a_split_prefills_currency_and_worth(client, pair, root_accounts):
    bank, usd = pair
    expense = make_account(client, "Fees", root_accounts["Expenses"])
    tid = client.post(
        "/api/transactions/",
        json={
            "date": LONG_AGO,
            "postings": [
                {"account": usd["aid"], "side": "debit", "amount": "100", "value": "8330"},
                {"account": expense["aid"], "side": "debit", "amount": "20"},
                {"account": bank["aid"], "side": "credit", "amount": "8350"},
            ],
        },
    ).json()["tid"]
    page = client.get(f"/transactions/{tid}/edit").text
    assert 'value="8330.00"' in page, "the foreign row shows its worth"
    assert page.count('name="value"') == 4, "three rows and the new-row template"
    assert page.count('class="row-worth" inputmode="decimal" autocomplete="off" hidden') == 3, "only the USD row shows a worth (the template and the two INR rows hide it)"
    assert f'hx-post="/transactions/{tid}/edit"' in page

    again = client.post(
        f"/transactions/{tid}/edit",
        data={
            "date": LONG_AGO,
            "currency": "INR",
            "account": [usd["aid"], expense["aid"], bank["aid"]],
            "side": ["debit", "debit", "credit"],
            "amount": ["100", "20", "8360"],
            "value": ["8340", "", ""],
        },
    )
    assert again.status_code == 200, again.text
    assert {p["account"]: p["value"] for p in client.get(f"/api/transactions/{tid}").json()["postings"]}[usd["aid"]] == "8340.00"


# ---- reading the numbers ------------------------------------------------------------------------------------------


def test_an_account_page_shows_units_and_the_holding(client, pair):
    bank, usd = pair
    client.post("/transactions", data=buy_usd_form(bank, usd))
    text = client.get(f"/accounts/{usd['aid']}").text
    hero = text[text.index("hero-balance"):]
    assert hero.startswith('hero-balance">100.00 USD')
    body = text_of(text)
    assert "Worth 8,350.00 INR at 83.50 per USD" in body
    assert "Invested 8,350.00" in body and "Gain 0.00" in body

    client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "price": "90"})
    body = text_of(client.get(f"/accounts/{usd['aid']}").text)
    assert "Worth 9,000.00 INR at 90.00 per USD" in body and "Gain 650.00" in body


def test_an_account_page_for_an_ordinary_account_has_no_holding(client, pair):
    bank, _ = pair
    body = text_of(client.get(f"/accounts/{bank['aid']}").text)
    assert "Invested" not in body and "Worth" not in body


def test_an_unpriced_holding_is_called_out_on_the_account_page(client, root_accounts):
    wise = make_account(client, "Wise", root_accounts["Assets"], "USD")
    salary = make_account(client, "US Salary", root_accounts["Income"], "USD")
    client.post(
        "/api/transactions/",
        json={
            "date": LONG_AGO,
            "currency": "USD",
            "postings": [
                {"account": wise["aid"], "side": "debit", "amount": "1000"},
                {"account": salary["aid"], "side": "credit", "amount": "1000"},
            ],
        },
    )
    body = text_of(client.get(f"/accounts/{wise['aid']}").text)
    assert "There is no USD price in INR yet" in body
    assert "partial" in client.get("/accounts").text
    dashboard = text_of(client.get("/").text)
    assert "Some holdings have no price yet" in dashboard


def test_the_accounts_list_labels_other_commodities(client, pair):
    bank, usd = pair
    client.post("/transactions", data=buy_usd_form(bank, usd))
    listing = text_of(client.get("/accounts").text)
    assert "100.00 USD" in listing and "91,650.00" in listing and "91,650.00 INR" not in listing


def test_the_transaction_list_shows_the_transactions_own_currency(client, pair, root_accounts):
    bank, usd = pair
    travel = make_account(client, "Travel", root_accounts["Expenses"], "USD")
    client.post("/transactions", data=buy_usd_form(bank, usd))
    client.post(
        "/transactions",
        data={"amount": "40", "from_account": usd["aid"], "to_account": travel["aid"], "date": LONG_AGO, "payee": "Hotel"},
    )
    listing = text_of(client.get("/transactions").text)
    assert "−40.00 USD" in listing and "8,350.00" in listing
    assert "8,350.00 INR" not in listing


def test_the_dashboard_totals_in_the_default_currency(client, pair):
    bank, usd = pair
    client.post("/transactions", data=buy_usd_form(bank, usd))
    body = text_of(client.get("/").text)
    assert "Net worth 100,000.00 INR" in body
    client.post("/settings/currency", data={"currency": "USD"})
    body = text_of(client.get("/").text)
    assert "Net worth 1,197.60 USD" in body


def test_moving_a_transaction_to_other_accounts_takes_the_new_currency(client, pair, root_accounts):
    bank, usd = pair
    card = make_account(client, "Card USD", root_accounts["Assets"], "USD")
    client.post("/transactions", data=buy_usd_form(bank, usd))
    client.post(
        "/transactions",
        data={"amount": "25", "from_account": usd["aid"], "to_account": card["aid"], "date": LONG_AGO},
    )
    transfer = latest(client)
    assert transfer["currency"] == "USD"

    savings = make_account(client, "Savings", root_accounts["Assets"], balance="1000")
    cash = make_account(client, "Cash", root_accounts["Assets"])
    response = client.post(
        f"/transactions/{transfer['tid']}/edit/simple",
        data={"amount": "30", "from_account": savings["aid"], "to_account": cash["aid"], "date": LONG_AGO},
    )
    assert response.status_code == 200, response.text
    moved = client.get(f"/api/transactions/{transfer['tid']}").json()
    assert moved["currency"] == "INR"
    assert all(p["value"] == p["amount"] == "30.00" for p in moved["postings"])
