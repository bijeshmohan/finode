"""One currency for the whole ledger: INR until the person picks another, a label and not a conversion."""

from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import select

from app import currencies
from app.models.transaction_history import TransactionHistory
from app.models.utils import normalize_amount

from .books import leg, post_account
from .svc import plain, services


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100", "100.00"),
        ("100.00000000", "100.00"),
        ("0.5", "0.50"),
        ("0.01250000", "0.0125"),
        ("1234.567", "1234.567"),
        ("0E-8", "0.00"),
        ("-12.5", "-12.50"),
        ("1E+2", "100.00"),
    ],
)
def test_normalize_amount(raw, expected):
    assert format(normalize_amount(Decimal(raw)), "f") == expected


# ---- the list of currencies ------------------------------------------------------------------------------------------


def test_the_currencies_are_the_iso_list_with_their_decimals():
    assert currencies.DEFAULT_CURRENCY == "INR"
    assert len(currencies.CURRENCIES) > 150
    assert currencies.find("inr").symbol == "₹" and currencies.find(" usd ").decimals == 2
    assert currencies.find("JPY").decimals == 0 and currencies.find("KWD").decimals == 3
    assert currencies.find("BTC") is None and currencies.find("") is None and currencies.find(None) is None
    assert all(len(code) == 3 and c.code == code for code, c in currencies.CURRENCIES.items())


# ---- the person's currency -------------------------------------------------------------------------------------------


def test_a_new_person_is_in_rupees(client, session):
    assert client.get("/api/profile/").json()["default_currency"] == "INR"
    assert services(session).reports.summary().currency == "INR"


def test_the_currency_can_be_changed_and_only_relabels(client, account, session):
    client.patch(f"/api/accounts/{account['aid']}", json={"balance": "1500.50"})
    changed = client.patch("/api/profile/", json={"default_currency": "usd"})
    assert changed.status_code == 200 and changed.json()["default_currency"] == "USD"
    assert services(session).reports.summary().currency == "USD"
    assert client.get("/api/budget/").json()["currency"] == "USD"
    assert client.get(f"/api/accounts/{account['aid']}").json()["balance"] == "1500.50", "nothing is converted"


def test_other_profile_edits_leave_the_currency_alone(client):
    client.patch("/api/profile/", json={"default_currency": "EUR"})
    client.patch("/api/profile/", json={"first_name": "Ada"})
    assert client.get("/api/profile/").json()["default_currency"] == "EUR"


@pytest.mark.parametrize("code", ["BTC", "INFY", "nope", "RS"])
def test_an_unknown_currency_is_refused(client, code):
    refused = client.patch("/api/profile/", json={"default_currency": code})
    assert refused.status_code == 400 and "unknown currency" in refused.json()["detail"]
    assert client.get("/api/profile/").json()["default_currency"] == "INR"


def test_an_empty_currency_is_refused(client):
    assert client.patch("/api/profile/", json={"default_currency": ""}).status_code in (400, 422)


def test_the_settings_page_changes_the_currency(client):
    page = client.get("/settings").text
    assert '<option value="INR" selected>' in page and '<option value="JPY"' in page
    assert "Changing it only changes the label" in page
    response = client.post("/settings/currency", data={"currency": "EUR"})
    assert (
        response.headers["HX-Redirect"].startswith("/settings") and "currency-updated" in response.headers["set-cookie"]
    )
    assert '<option value="EUR" selected>' in client.get("/settings").text
    bad = client.post("/settings/currency", data={"currency": "BTC"})
    assert bad.status_code == 400 and "unknown currency" in bad.text


def test_amounts_wear_the_chosen_currency(client, root_accounts):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "250"})
    assert '<span class="cur">&#8377;</span>' in client.get("/budget").text
    client.patch("/api/profile/", json={"default_currency": "USD"})
    page = client.get("/budget").text
    assert '<span class="cur">&#8377;</span>' not in page and "<small>USD</small>" in page


# ---- how many decimals an amount may have ----------------------------------------------------------------------------


def post(client, a, b, amount):
    return client.post(
        "/api/transactions/",
        json={
            "postings": [
                leg(a, "debit", amount),
                leg(b, "credit", amount),
            ]
        },
    )


def test_rupees_have_two_decimals(client, account, expense_account):
    assert post(client, expense_account, account, "10.25").status_code == 201
    refused = post(client, expense_account, account, "10.255")
    assert refused.status_code == 400 and "INR amounts can have at most 2 decimal places" in refused.json()["detail"]


def test_yen_have_none_and_the_dinar_has_three(client, account, expense_account):
    client.patch("/api/profile/", json={"default_currency": "JPY"})
    refused = post(client, expense_account, account, "10.5")
    assert refused.status_code == 400 and "JPY amounts can have at most 0 decimal places" in refused.json()["detail"]
    assert post(client, expense_account, account, "10").status_code == 201
    client.patch("/api/profile/", json={"default_currency": "KWD"})
    assert post(client, expense_account, account, "10.125").status_code == 201


def test_opening_balances_follow_the_same_rule(client, root_accounts):
    refused = post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "1.234"})
    assert refused.status_code == 400 and "at most 2 decimal places" in refused.json()["detail"]
    client.patch("/api/profile/", json={"default_currency": "JPY"})
    assert (
        post_account(client, {"name": "Wallet", "parent_id": root_accounts["Assets"], "balance": "1500"}).status_code
        == 201
    )


def test_the_budget_follows_it_too(client, root_accounts, expense_account):
    post_account(client, {"name": "Bank", "parent_id": root_accounts["Assets"], "balance": "500"})
    refused = client.put(f"/api/budget/categories/{expense_account['aid']}", json={"amount": "1.234"})
    assert refused.status_code == 400 and "decimal places" in refused.json()["detail"]


# ---- what is gone ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["/api/commodities/", "/api/prices/", "/api/prices/rate", "/commodities", "/commodities/prices"]
)
def test_assets_and_prices_are_gone(client, path):
    assert client.get(path).status_code in (404, 405)
    assert client.post(path, json={}).status_code in (404, 405)


def test_the_api_has_no_commodities_values_or_currencies_per_record(client, account, expense_account, session):
    made = post(client, expense_account, account, "10").json()
    assert "currency" not in made and all("value" not in p for p in made["postings"])
    read = client.get(f"/api/accounts/{account['aid']}").json()
    assert "commodity" not in read and "unpriced" not in read
    assert client.get(f"/api/accounts/{account['aid']}/holding").status_code in (404, 405)
    summary = plain(services(session).reports.summary())
    assert "unpriced" not in summary
    trial = client.get("/api/reports/trial-balance").json()
    assert "totals" not in trial and trial["currency"] == "INR"


def test_extra_fields_from_older_clients_are_ignored(client, root_accounts, account, expense_account):
    made = client.post(
        "/api/transactions/",
        json={
            "currency": "USD",
            "postings": [
                {"category": expense_account["aid"], "side": "debit", "amount": "10", "value": "3"},
                {"account": account["aid"], "side": "credit", "amount": "10", "value": "3"},
            ],
        },
    )
    assert made.status_code == 201
    created = post_account(client, {"name": "Old", "parent_id": root_accounts["Assets"], "commodity": "USD"})
    assert created.status_code == 201


def test_the_account_form_has_no_commodity_fields(client):
    page = client.get("/accounts/new").text
    assert 'name="commodity"' not in page and 'name="balance_value"' not in page and "Balance is worth" not in page
    form = client.get("/transactions/new").text
    assert 'name="value"' not in form and 'name="currency"' not in form and "row-worth" not in form


# ---- entries made before finode kept one currency ----------------------------------------------------------------------


def test_old_history_rows_still_read_and_do_not_count_as_a_change(client, session, account, expense_account):
    made = post(client, expense_account, account, "10").json()
    tid = UUID(made["tid"])
    [row] = session.exec(select(TransactionHistory).where(TransactionHistory.transaction_id == tid)).all()
    # What an older finode wrote: a currency and a worth in every posting.
    old = dict(row.snapshot)
    old["currency_id"] = "00000000-0000-4000-8000-000000000999"
    old["postings"] = [{**p, "value": p["amount"]} for p in old["postings"]]
    row.snapshot = old
    session.add(row)
    session.commit()
    history = plain(services(session).transactions.history(tid))
    assert len(history) == 1 and history[0]["postings"][0]["amount"] == "10.00" and "currency" not in history[0]
    saved = client.patch(
        f"/api/transactions/{tid}",
        json={
            "payee": made["payee"],
            "postings": [
                leg(expense_account, "debit", "10"),
                leg(account, "credit", "10"),
            ],
        },
    )
    assert saved.status_code == 200
    assert len(services(session).transactions.history(tid)) == 1, "saving it unchanged adds nothing"
    client.patch(f"/api/transactions/{tid}", json={"payee": "Changed"})
    assert len(services(session).transactions.history(tid)) == 2
