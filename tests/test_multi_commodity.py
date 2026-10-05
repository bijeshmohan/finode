"""Accounts holding USD, BTC or shares next to INR: conversions, valuation and the rules around them."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.commodity import Commodity

from .conftest import TEST_USER_ID


TODAY = date.today()
LONG_AGO = TODAY - timedelta(days=60)
LAST_WEEK = TODAY - timedelta(days=7)


@pytest.fixture
def infy(session):
    session.add(Commodity(code="INFY", name="Infosys", kind="stock", decimals=0, user=TEST_USER_ID))
    session.add(Commodity(code="NIFTYBEES", name="Nifty fund", kind="fund", decimals=3, user=TEST_USER_ID))
    session.commit()


def make(client, name, parent, commodity=None, **extra):
    body = {"name": name, "parent_id": parent, **extra}
    if commodity:
        body["commodity"] = commodity
    response = client.post("/accounts/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def get(client, aid):
    return client.get(f"/accounts/{aid}").json()


def post(client, postings, currency=None, when=LONG_AGO, expect=201):
    body = {
        "date": str(when),
        "postings": [
            {"account": a, "side": s, "amount": str(m), **({"value": str(v)} if v is not None else {})}
            for a, s, m, v in postings
        ],
    }
    if currency:
        body["currency"] = currency
    response = client.post("/transactions/", json=body)
    assert response.status_code == expect, response.text
    return response.json()


@pytest.fixture
def wallet(client, root_accounts):
    """INR bank with 1,00,000, a USD account, and an expense account."""
    bank = make(client, "HDFC", root_accounts["Assets"], balance="100000.00")
    usd = make(client, "Wise USD", root_accounts["Assets"], "USD")
    return {"bank": bank["aid"], "usd": usd["aid"]}


# ---- buying a currency ---------------------------------------------------------------------


def test_buying_usd_with_inr(client, wallet):
    txn = post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])

    assert txn["currency"] == "INR"
    values = {p["account"]: (p["amount"], p["value"]) for p in txn["postings"]}
    assert values[wallet["usd"]] == ("100.00", "8350.00")
    assert values[wallet["bank"]] == ("8350.00", "8350.00")
    assert get(client, wallet["usd"])["balance"] == "100.00"
    assert get(client, wallet["usd"])["commodity"] == "USD"
    assert get(client, wallet["bank"])["balance"] == "91650.00"


def test_the_conversion_becomes_the_rate(client, wallet):
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    rate = client.get("/prices/rate", params={"commodity": "USD", "quote": "INR"}).json()
    assert Decimal(rate["rate"]) == Decimal("83.5")
    inverse = client.get("/prices/rate", params={"commodity": "INR", "quote": "USD"}).json()
    assert Decimal(inverse["rate"]).quantize(Decimal("0.00001")) == Decimal("0.01198")


def test_net_worth_values_every_holding_in_the_default_currency(client, wallet):
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    summary = client.get("/reports/summary").json()
    assert summary["currency"] == "INR"
    assert Decimal(summary["assets"]) == Decimal("100000.00")
    assert Decimal(summary["net_worth"]) == Decimal("100000.00")
    assert summary["unpriced"] is False


def test_the_root_total_is_in_the_default_currency(client, wallet, root_accounts):
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    root = get(client, root_accounts["Assets"])
    assert root["commodity"] == "INR" and Decimal(root["balance"]) == Decimal("100000.00")


def test_a_later_price_revalues_the_holding(client, wallet):
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    client.post("/prices/", json={"commodity": "USD", "quote": "INR", "date": str(TODAY), "price": "90"})
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("100650.00")


def test_deleting_your_price_falls_back_to_the_conversion_rate(client, wallet):
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    price = client.post("/prices/", json={"commodity": "USD", "quote": "INR", "price": "90"}).json()
    assert client.delete(f"/prices/{price['pid']}").status_code == 204
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("100000.00")


# ---- the rules ---------------------------------------------------------------------------------


def test_postings_in_different_commodities_without_values_do_not_balance(client, wallet):
    response = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "postings": [
                {"account": wallet["usd"], "side": "debit", "amount": "100"},
                {"account": wallet["bank"], "side": "credit", "amount": "8350"},
            ],
        },
    )
    assert response.status_code == 422
    assert "must balance" in response.text


def test_a_missing_value_is_explained(client, wallet, expense_account):
    response = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "postings": [
                {"account": wallet["usd"], "side": "debit", "amount": "100", "value": "8350"},
                {"account": wallet["bank"], "side": "credit", "amount": "8300", "value": "8300"},
            ],
        },
    )
    assert response.status_code == 400
    assert "must balance in INR" in response.json()["detail"]


def test_value_is_required_for_a_foreign_posting_when_others_have_one(client, wallet):
    response = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "postings": [
                {"account": wallet["usd"], "side": "debit", "amount": "100"},
                {"account": wallet["bank"], "side": "credit", "amount": "8350", "value": "8350"},
            ],
        },
    )
    assert response.status_code == 400
    assert "say what 100 USD is worth in INR" in response.json()["detail"]


def test_a_value_on_a_posting_in_the_transaction_currency_must_match_its_amount(client, wallet, expense_account):
    response = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "100", "value": "90"},
                {"account": wallet["bank"], "side": "credit", "amount": "100"},
            ],
        },
    )
    assert response.status_code == 400
    assert "leave the value out" in response.json()["detail"]


def test_a_value_equal_to_the_amount_is_accepted(client, wallet, expense_account):
    post(client, [(expense_account["aid"], "debit", 100, 100), (wallet["bank"], "credit", 100, None)])


def test_amounts_respect_the_decimals_of_their_commodity(client, wallet, expense_account):
    response = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "10.005"},
                {"account": wallet["bank"], "side": "credit", "amount": "10.005"},
            ],
        },
    )
    assert response.status_code == 400
    assert "INR amounts can have at most 2 decimal places" in response.json()["detail"]


def test_values_respect_the_decimals_of_the_currency(client, wallet):
    response = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "postings": [
                {"account": wallet["usd"], "side": "debit", "amount": "100", "value": "8350.123"},
                {"account": wallet["bank"], "side": "credit", "amount": "8350.123", "value": None},
            ],
        },
    )
    assert response.status_code == 400
    assert "at most 2 decimal places" in response.json()["detail"]


def test_a_transaction_can_be_in_the_currency_of_its_accounts(client, wallet, root_accounts):
    travel = make(client, "Travel", root_accounts["Expenses"], "USD")
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    txn = post(
        client, [(travel["aid"], "debit", 40, None), (wallet["usd"], "credit", 40, None)], currency="USD", when=LAST_WEEK
    )
    assert txn["currency"] == "USD"
    assert get(client, wallet["usd"])["balance"] == "60.00"
    assert get(client, travel["aid"])["balance"] == "40.00"


def test_an_unknown_transaction_currency_is_refused(client, wallet, expense_account):
    response = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "currency": "ZZZ",
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "5"},
                {"account": wallet["bank"], "side": "credit", "amount": "5"},
            ],
        },
    )
    assert response.status_code == 400 and "unknown currency" in response.json()["detail"]


# ---- spending abroad: valued at the day's rate ----------------------------------------------------


def test_spending_usd_counts_in_inr_at_the_rate_of_the_day(client, wallet, root_accounts):
    travel = make(client, "Travel", root_accounts["Expenses"], "USD")
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)], when=LONG_AGO)
    post(client, [(travel["aid"], "debit", 40, None), (wallet["usd"], "credit", 40, None)], "USD", when=LAST_WEEK)

    summary = client.get(
        "/reports/summary", params={"date_from": str(LAST_WEEK), "date_to": str(TODAY)}
    ).json()
    assert Decimal(summary["expenses"]) == Decimal("3340.00")
    assert summary["currency"] == "INR" and summary["unpriced"] is False


# ---- buying shares and coins ---------------------------------------------------------------------------


def test_buying_stock(client, root_accounts, infy):
    bank = make(client, "Zerodha cash", root_accounts["Assets"], balance="200000.00")
    group = make(client, "Zerodha", root_accounts["Assets"])
    holding = make(client, "INFY", group["aid"], "INFY")
    assert holding["commodity"] == "INFY"

    post(client, [(holding["aid"], "debit", 10, 15000), (bank["aid"], "credit", 15000, None)])

    assert get(client, holding["aid"])["balance"] == "10.00"
    rate = client.get("/prices/rate", params={"commodity": "INFY", "quote": "INR"}).json()
    assert Decimal(rate["rate"]) == Decimal("1500")
    assert Decimal(get(client, group["aid"])["balance"]) == Decimal("15000.00")
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("200000.00")


def test_shares_can_be_whole_only(client, root_accounts, infy):
    bank = make(client, "Cash", root_accounts["Assets"], balance="200000.00")
    holding = make(client, "INFY", root_accounts["Assets"], "INFY")
    response = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "postings": [
                {"account": holding["aid"], "side": "debit", "amount": "2.5", "value": "3750"},
                {"account": bank["aid"], "side": "credit", "amount": "3750"},
            ],
        },
    )
    assert response.status_code == 400
    assert "INFY amounts can have at most 0 decimal places" in response.json()["detail"]


def test_fractional_units_of_a_fund_and_a_coin(client, root_accounts, infy):
    bank = make(client, "Cash", root_accounts["Assets"], balance="200000.00")
    fund = make(client, "Nifty ETF", root_accounts["Assets"], "NIFTYBEES")
    btc = make(client, "Bitcoin", root_accounts["Assets"], "BTC")
    post(client, [(fund["aid"], "debit", "12.345", 3000), (bank["aid"], "credit", 3000, None)])
    post(client, [(btc["aid"], "debit", "0.01234567", 75000), (bank["aid"], "credit", 75000, None)])

    assert get(client, fund["aid"])["balance"] == "12.345"
    assert get(client, btc["aid"])["balance"] == "0.01234567"
    summary = client.get("/reports/summary").json()
    assert Decimal(summary["net_worth"]) == Decimal("200000.00")


def test_bitcoin_revalues_with_a_newer_price(client, root_accounts):
    bank = make(client, "Cash", root_accounts["Assets"], balance="3000000.00")
    btc = make(client, "Bitcoin", root_accounts["Assets"], "BTC")
    post(client, [(btc["aid"], "debit", "0.5", 2000000), (bank["aid"], "credit", 2000000, None)])
    # cash 1,000,000 + 0.5 BTC at the purchase rate (2,000,000)
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("3000000.00")

    client.post("/prices/", json={"commodity": "BTC", "quote": "INR", "price": "5000000"})
    # cash 1,000,000 + 0.5 BTC at 5,000,000
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("3500000.00")


def test_selling_with_a_gain_is_the_users_own_transaction(client, root_accounts):
    bank = make(client, "Cash", root_accounts["Assets"], balance="100000.00")
    btc = make(client, "Bitcoin", root_accounts["Assets"], "BTC")
    gain = make(client, "Capital Gain", root_accounts["Income"])
    post(client, [(btc["aid"], "debit", "1", 50000), (bank["aid"], "credit", 50000, None)])
    # sell it all for 65,000: 15,000 of it is gain
    post(
        client,
        [
            (bank["aid"], "debit", 65000, None),
            (btc["aid"], "credit", "1", 50000),
            (gain["aid"], "credit", 15000, None),
        ],
        when=LAST_WEEK,
    )
    assert get(client, btc["aid"])["balance"] == "0.00"
    assert Decimal(get(client, bank["aid"])["balance"]) == Decimal("115000.00")
    assert Decimal(get(client, gain["aid"])["balance"]) == Decimal("15000.00")


# ---- opening balances in another commodity --------------------------------------------------------


def test_an_opening_balance_in_another_commodity_needs_to_be_valued(client, root_accounts):
    response = client.post(
        "/accounts/",
        json={"name": "Wise", "parent_id": root_accounts["Assets"], "commodity": "USD", "balance": "100"},
    )
    assert response.status_code == 400
    assert "no USD price is known yet" in response.json()["detail"]
    # nothing was half-created
    assert "Wise" not in {a["name"] for a in client.get("/accounts/").json()}


def test_an_opening_balance_can_be_given_a_worth(client, root_accounts):
    wise = client.post(
        "/accounts/",
        json={
            "name": "Wise",
            "parent_id": root_accounts["Assets"],
            "commodity": "USD",
            "balance": "100",
            "balance_value": "8300",
        },
    ).json()
    assert wise["balance"] == "100.00"
    txn = client.get("/transactions/").json()[0]
    assert txn["currency"] == "INR"
    assert sorted((p["amount"], p["value"]) for p in txn["postings"]) == [("100.00", "8300.00"), ("8300.00", "8300.00")]
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("8300.00")
    opening = next(a for a in client.get("/accounts/").json() if a["name"] == "Opening Balances")
    assert Decimal(opening["balance"]) == Decimal("8300.00")


def test_an_opening_balance_uses_the_latest_price_when_there_is_one(client, root_accounts):
    client.post("/prices/", json={"commodity": "USD", "quote": "INR", "date": str(LAST_WEEK), "price": "83"})
    wise = make(client, "Wise", root_accounts["Assets"], "USD", balance="100")
    assert wise["balance"] == "100.00"
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("8300.00")


def test_editing_a_balance_in_another_commodity_uses_the_price(client, wallet):
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    updated = client.patch(f"/accounts/{wallet['usd']}", json={"balance": "150"})
    assert updated.status_code == 200 and updated.json()["balance"] == "150.00"
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("100000.00") + Decimal("4175.00")


# ---- accounts and their commodity ----------------------------------------------------------------------


def test_a_child_inherits_the_commodity_of_its_parent(client, wallet, root_accounts):
    group = make(client, "Foreign", root_accounts["Assets"], "USD")
    child = make(client, "Card", group["aid"])
    assert child["commodity"] == "USD"
    assert make(client, "Cash", group["aid"], "INR")["commodity"] == "INR"


def test_an_unknown_commodity_is_refused(client, root_accounts):
    response = client.post("/accounts/", json={"name": "X", "parent_id": root_accounts["Assets"], "commodity": "ZZZ"})
    assert response.status_code == 400 and "unknown commodity" in response.json()["detail"]


def test_the_commodity_is_case_insensitive(client, root_accounts):
    assert make(client, "Euro", root_accounts["Assets"], "eur")["commodity"] == "EUR"


def test_commodity_can_change_until_there_are_postings(client, wallet, root_accounts):
    fresh = make(client, "Later", root_accounts["Assets"])
    assert client.patch(f"/accounts/{fresh['aid']}", json={"commodity": "EUR"}).json()["commodity"] == "EUR"

    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    blocked = client.patch(f"/accounts/{wallet['usd']}", json={"commodity": "EUR"})
    assert blocked.status_code == 400 and "has postings" in blocked.json()["detail"]
    assert get(client, wallet["usd"])["commodity"] == "USD"


def test_roots_and_system_accounts_cannot_change_commodity(client, root_accounts):
    assert client.patch(f"/accounts/{root_accounts['Assets']}", json={"commodity": "USD"}).status_code == 400


# ---- groups mixing commodities ----------------------------------------------------------------------------


def test_a_group_totals_its_children_in_its_own_commodity(client, wallet, root_accounts):
    group = make(client, "Savings", root_accounts["Assets"])
    inr = make(client, "FD", group["aid"])
    usd = make(client, "Dollars", group["aid"], "USD")
    post(client, [(inr["aid"], "debit", 1000, None), (wallet["bank"], "credit", 1000, None)])
    post(client, [(usd["aid"], "debit", 10, 835), (wallet["bank"], "credit", 835, None)])
    assert Decimal(get(client, group["aid"])["balance"]) == Decimal("1835.00")


def test_an_unpriced_holding_is_flagged_not_dropped(client, root_accounts):
    wise = make(client, "Wise", root_accounts["Assets"], "USD")
    salary = make(client, "US Salary", root_accounts["Income"], "USD")
    post(client, [(wise["aid"], "debit", 1000, None), (salary["aid"], "credit", 1000, None)], "USD")

    assert get(client, wise["aid"])["balance"] == "1000.00"
    assets = get(client, root_accounts["Assets"])
    assert Decimal(assets["balance"]) == Decimal("0.00") and assets["unpriced"] is True
    summary = client.get("/reports/summary").json()
    assert summary["unpriced"] is True


def test_pricing_it_later_resolves_the_flag(client, root_accounts):
    wise = make(client, "Wise", root_accounts["Assets"], "USD")
    salary = make(client, "US Salary", root_accounts["Income"], "USD")
    post(client, [(wise["aid"], "debit", 1000, None), (salary["aid"], "credit", 1000, None)], "USD")
    client.post("/prices/", json={"commodity": "USD", "quote": "INR", "price": "83"})
    assets = get(client, root_accounts["Assets"])
    assert Decimal(assets["balance"]) == Decimal("83000.00") and assets["unpriced"] is False


def test_a_register_values_other_commodities_at_the_rate_of_the_day(client, wallet, root_accounts):
    group = make(client, "Savings", root_accounts["Assets"])
    usd = make(client, "Dollars", group["aid"], "USD")
    post(client, [(usd["aid"], "debit", 10, 800), (wallet["bank"], "credit", 800, None)], when=LONG_AGO)
    post(client, [(usd["aid"], "debit", 10, 900), (wallet["bank"], "credit", 900, None)], when=LAST_WEEK)
    entries = client.get(f"/accounts/{group['aid']}/register").json()
    assert [Decimal(e["change"]) for e in entries] == [Decimal("800.00"), Decimal("900.00")]
    assert [Decimal(e["balance"]) for e in entries] == [Decimal("800.00"), Decimal("1700.00")]
    own = client.get(f"/accounts/{usd['aid']}/register").json()
    assert [Decimal(e["change"]) for e in own] == [Decimal("10"), Decimal("10")]


# ---- editing and deleting ---------------------------------------------------------------------------------


def test_editing_a_conversion_changes_the_rate(client, wallet):
    txn = post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    response = client.patch(
        f"/transactions/{txn['tid']}",
        json={
            "postings": [
                {"account": wallet["usd"], "side": "debit", "amount": "100", "value": "8400"},
                {"account": wallet["bank"], "side": "credit", "amount": "8400"},
            ]
        },
    )
    assert response.status_code == 200
    rate = client.get("/prices/rate", params={"commodity": "USD", "quote": "INR"}).json()
    assert Decimal(rate["rate"]) == Decimal("84")


def test_deleting_a_conversion_forgets_its_rate(client, wallet):
    txn = post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    assert client.delete(f"/transactions/{txn['tid']}").status_code == 204
    rate = client.get("/prices/rate", params={"commodity": "USD", "quote": "INR"}).json()
    assert rate["rate"] is None


def test_changing_the_currency_needs_new_postings(client, wallet, expense_account):
    txn = post(client, [(expense_account["aid"], "debit", 10, None), (wallet["bank"], "credit", 10, None)])
    response = client.patch(f"/transactions/{txn['tid']}", json={"currency": "USD"})
    assert response.status_code == 400 and "entering its postings again" in response.json()["detail"]


def test_updating_without_touching_the_currency_keeps_it(client, wallet, root_accounts):
    travel = make(client, "Travel", root_accounts["Expenses"], "USD")
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    txn = post(client, [(travel["aid"], "debit", 40, None), (wallet["usd"], "credit", 40, None)], "USD")
    response = client.patch(f"/transactions/{txn['tid']}", json={"payee": "Hotel"})
    assert response.status_code == 200 and response.json()["currency"] == "USD"
    again = client.patch(
        f"/transactions/{txn['tid']}",
        json={
            "postings": [
                {"account": travel["aid"], "side": "debit", "amount": "55"},
                {"account": wallet["usd"], "side": "credit", "amount": "55"},
            ]
        },
    )
    assert again.status_code == 200 and again.json()["currency"] == "USD"


# ---- the default currency ---------------------------------------------------------------------------------------


def test_the_default_currency_can_change_and_totals_follow(client, wallet, root_accounts):
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    response = client.patch("/profile/", json={"default_currency": "usd"})
    assert response.status_code == 200 and response.json()["default_currency"] == "USD"

    summary = client.get("/reports/summary").json()
    assert summary["currency"] == "USD"
    assert Decimal(summary["net_worth"]) == (Decimal("100000") / Decimal("83.5")).quantize(Decimal("0.01"))
    assert get(client, root_accounts["Assets"])["commodity"] == "USD"
    # existing accounts keep what they hold; new ones under a top-level account follow the default
    assert get(client, wallet["bank"])["commodity"] == "INR"
    assert make(client, "New", root_accounts["Assets"])["commodity"] == "USD"


def test_only_a_currency_can_be_the_default(client):
    assert client.patch("/profile/", json={"default_currency": "BTC"}).status_code == 400
    assert client.patch("/profile/", json={"default_currency": "ZZZ"}).status_code == 400
    assert client.patch("/profile/", json={"default_currency": ""}).status_code == 422
    assert client.get("/profile/").json()["default_currency"] == "INR"


def test_other_profile_edits_leave_the_currency_alone(client):
    client.patch("/profile/", json={"default_currency": "EUR"})
    client.patch("/profile/", json={"first_name": "Asha"})
    assert client.get("/profile/").json()["default_currency"] == "EUR"


# ---- invested and gain ------------------------------------------------------------------------------------------


def test_a_holding_reports_what_was_invested_and_what_it_is_worth(client, root_accounts):
    bank = make(client, "Cash", root_accounts["Assets"], balance="100000.00")
    btc = make(client, "Bitcoin", root_accounts["Assets"], "BTC")
    post(client, [(btc["aid"], "debit", "0.5", 50000), (bank["aid"], "credit", 50000, None)])

    holding = client.get(f"/accounts/{btc['aid']}/holding").json()
    assert holding["commodity"] == "BTC" and holding["currency"] == "INR"
    assert Decimal(holding["quantity"]) == Decimal("0.5")
    assert Decimal(holding["value"]) == Decimal("50000.00")
    assert Decimal(holding["invested"]) == Decimal("50000.00") and Decimal(holding["gain"]) == 0

    client.post("/prices/", json={"commodity": "BTC", "quote": "INR", "price": "130000"})
    holding = client.get(f"/accounts/{btc['aid']}/holding").json()
    assert Decimal(holding["value"]) == Decimal("65000.00")
    assert Decimal(holding["gain"]) == Decimal("15000.00")
    assert Decimal(holding["rate"]) == Decimal("130000")


def test_invested_converts_a_foreign_transaction_currency(client, root_accounts, wallet):
    travel = make(client, "Dollar pot", root_accounts["Assets"], "EUR")
    post(client, [(wallet["usd"], "debit", 100, 8350), (wallet["bank"], "credit", 8350, None)])
    # buy 90 EUR with 100 USD: a transaction in USD
    post(client, [(travel["aid"], "debit", 90, 100), (wallet["usd"], "credit", 100, None)], "USD", when=LAST_WEEK)
    holding = client.get(f"/accounts/{travel['aid']}/holding").json()
    # 100 USD at the 83.50 the dollars cost
    assert Decimal(holding["invested"]) == Decimal("8350.00")
    assert Decimal(holding["value"]).quantize(Decimal("0.01")) == Decimal("8350.00")


def test_a_holding_without_a_price_has_no_value(client, root_accounts):
    wise = make(client, "Wise", root_accounts["Assets"], "USD")
    salary = make(client, "US Salary", root_accounts["Income"], "USD")
    post(client, [(wise["aid"], "debit", 1000, None), (salary["aid"], "credit", 1000, None)], "USD")
    holding = client.get(f"/accounts/{wise['aid']}/holding").json()
    assert holding["value"] is None and holding["gain"] is None and holding["rate"] is None


def test_only_accounts_holding_something_else_have_a_holding(client, wallet, root_accounts):
    assert client.get(f"/accounts/{wallet['bank']}/holding").status_code == 404
    assert client.get(f"/accounts/{root_accounts['Assets']}/holding").status_code == 404
    group = make(client, "Foreign", root_accounts["Assets"], "USD")
    make(client, "Card", group["aid"])
    assert client.get(f"/accounts/{group['aid']}/holding").status_code == 404, "groups have no single holding"
    assert client.get(f"/accounts/{wallet['usd']}/holding").status_code == 200


# ---- other users' commodities, and balances after the default changed -----------------------------------------


def test_another_users_commodity_cannot_be_used(session, client, root_accounts, wallet):
    from uuid import UUID

    session.add(Commodity(code="THEIRS", name="Theirs", kind="stock", user=UUID(int=2)))
    session.commit()
    created = client.post("/accounts/", json={"name": "X", "parent_id": root_accounts["Assets"], "commodity": "THEIRS"})
    assert created.status_code == 400 and "unknown commodity" in created.json()["detail"]
    moved = client.patch(f"/accounts/{wallet['usd']}", json={"commodity": "THEIRS"})
    assert moved.status_code == 400
    in_theirs = client.post(
        "/transactions/",
        json={
            "date": str(LONG_AGO),
            "currency": "THEIRS",
            "postings": [
                {"account": wallet["bank"], "side": "credit", "amount": "5", "value": "5"},
                {"account": wallet["usd"], "side": "debit", "amount": "5", "value": "5"},
            ],
        },
    )
    assert in_theirs.status_code == 400 and "unknown currency" in in_theirs.json()["detail"]
    assert client.patch("/profile/", json={"default_currency": "THEIRS"}).status_code == 400
    assert client.post("/prices/", json={"commodity": "THEIRS", "quote": "INR", "price": "1"}).status_code == 404


def test_a_failed_balance_edit_changes_nothing(client, root_accounts):
    wise = make(client, "Wise", root_accounts["Assets"], "USD")
    response = client.patch(f"/accounts/{wise['aid']}", json={"balance": "50"})
    assert response.status_code == 400 and "no USD price is known yet" in response.json()["detail"]
    assert get(client, wise["aid"])["balance"] == "0.00"
    assert client.get("/transactions/").json() == []


def test_the_worth_of_an_opening_balance_is_asked_in_the_opening_balances_currency(client, root_accounts):
    first = make(client, "Bank", root_accounts["Assets"], balance="1000")  # creates Opening Balances in INR
    assert first["commodity"] == "INR"
    client.patch("/profile/", json={"default_currency": "USD"})
    response = client.post(
        "/accounts/", json={"name": "Wise", "parent_id": root_accounts["Assets"], "balance": "100"}
    )
    assert response.status_code == 400
    assert "say what 100 USD is worth in INR" in response.json()["detail"]
    page = client.get("/app/accounts/new").text
    assert "Holds something other than USD?" in page and "in INR, only if it holds something else" in page


def test_a_negative_worth_is_refused(client, root_accounts):
    response = client.post(
        "/accounts/",
        json={"name": "Wise", "parent_id": root_accounts["Assets"], "commodity": "USD", "balance": "5", "balance_value": "-1"},
    )
    assert response.status_code == 422
