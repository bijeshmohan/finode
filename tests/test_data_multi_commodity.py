"""Exporting and importing ledgers with several currencies, conversions, shares and prices."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.ledger import parse
from app.models.commodity import Commodity
from app.repositories import AccountRepository, CommodityRepository, ProfileRepository, TransactionRepository
from app.repositories.price import PriceRepository
from app.services import AccountService, DataService
from app.services.data import ImportRejected
from app.services.prices import PriceService

from .conftest import TEST_USER_ID


NEWCOMER = UUID("00000000-0000-4000-8000-000000000009")
LONG_AGO = date.today() - timedelta(days=60)
LAST_WEEK = date.today() - timedelta(days=7)


def service_for(session: Session, uid: UUID) -> DataService:
    ar, tr, pr, cr = (
        AccountRepository(session, uid),
        TransactionRepository(session, uid),
        ProfileRepository(session, uid),
        CommodityRepository(session, uid),
    )
    prices = PriceService(PriceRepository(session, uid), tr, cr)
    return DataService(AccountService(ar, tr, pr, cr, prices), ar, tr, pr)


def make(client, name, parent, commodity=None, **extra):
    body = {"name": name, "parent_id": parent, **extra}
    if commodity:
        body["commodity"] = commodity
    response = client.post("/accounts/", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def post(client, postings, currency=None, when=LONG_AGO, payee=None):
    response = client.post(
        "/transactions/",
        json={
            "date": str(when),
            "payee": payee,
            "currency": currency,
            "postings": [
                {"account": a, "side": s, "amount": str(m), **({"value": str(v)} if v is not None else {})}
                for a, s, m, v in postings
            ],
        },
    )
    assert response.status_code == 201, response.text


@pytest.fixture
def rich(client, root_accounts, session):
    """INR bank, USD account, Infosys shares and some Bitcoin, with prices and a sale."""
    session.add(Commodity(code="INFY", name="Infosys", kind="stock", decimals=0, user=TEST_USER_ID))
    session.commit()
    bank = make(client, "HDFC", root_accounts["Assets"], balance="500000.00", details="Salary account")
    usd = make(client, "Wise", root_accounts["Assets"], "USD")
    broker = make(client, "Zerodha", root_accounts["Assets"])
    infy = make(client, "INFY", broker["aid"], "INFY")
    btc = make(client, "Bitcoin", root_accounts["Assets"], "BTC")
    gain = make(client, "Capital Gain", root_accounts["Income"])
    travel = make(client, "Travel", root_accounts["Expenses"], "USD")
    post(client, [(usd["aid"], "debit", 100, 8350), (bank["aid"], "credit", 8350, None)], payee="Buy USD")
    post(client, [(infy["aid"], "debit", 10, 15000), (bank["aid"], "credit", 15000, None)], payee="Buy INFY")
    post(client, [(btc["aid"], "debit", "0.01234567", 75000), (bank["aid"], "credit", 75000, None)])
    post(client, [(travel["aid"], "debit", 40, None), (usd["aid"], "credit", 40, None)], "USD", when=LAST_WEEK)
    post(
        client,
        [(bank["aid"], "debit", 17000, None), (infy["aid"], "credit", 5, 7500), (gain["aid"], "credit", 9500, None)],
        when=LAST_WEEK,
        payee="Sell INFY",
    )
    client.post("/prices/", json={"commodity": "INFY", "quote": "INR", "date": str(LAST_WEEK), "price": "1650.5"})
    return {"bank": bank, "usd": usd, "infy": infy, "btc": btc}


# ---- export -----------------------------------------------------------------------------------------------------


def test_the_ledger_export_labels_amounts_and_writes_conversions(client, rich):
    text = client.get("/export").text
    assert "commodity 1,000.00 USD" in text
    assert "commodity 1,000 INFY  ; name:Infosys, kind:stock" in text
    assert "commodity 1,000.00000000 BTC" in text
    assert f"P {LAST_WEEK} INFY 1650.50 INR" in text
    assert "100.00 USD @@ 8350.00 INR" in text
    assert "10.00 INFY @@ 15000.00 INR" in text
    assert "0.01234567 BTC @@ 75000.00 INR" in text
    assert "-5.00 INFY @@ 7500.00 INR" in text
    assert "40.00 USD" in text and "-40.00 USD" in text
    journal = parse(text)
    assert journal.errors == []


def test_a_single_currency_export_has_no_commodities(client, account, expense_account):
    client.post(
        "/transactions/",
        json={
            "postings": [
                {"account": expense_account["aid"], "side": "debit", "amount": "9.99"},
                {"account": account["aid"], "side": "credit", "amount": "9.99"},
            ]
        },
    )
    text = client.get("/export").text
    assert "INR" not in text and "commodity" not in text and "@@" not in text
    assert "9.99" in text
    assert client.get("/export?format=csv").content.decode("utf-8-sig").splitlines()[0] == "date,payee,note,account,debit,credit"


def test_the_csv_export_adds_commodity_columns_when_needed(client, rich):
    lines = client.get("/export?format=csv").content.decode("utf-8-sig").splitlines()
    assert lines[0] == "date,payee,note,account,debit,credit,commodity,value,currency"
    rows = [line.split(",") for line in lines[1:]]
    buy = next(r for r in rows if r[3] == "Assets:Wise" and r[4] == "100.00")
    assert buy[6:] == ["USD", "8350.00", "INR"]
    coin = next(r for r in rows if r[3] == "Assets:Bitcoin")
    assert coin[4] == "0.01234567" and coin[6:] == ["BTC", "75000.00", "INR"]
    spend = next(r for r in rows if r[3] == "Expenses:Travel")
    assert spend[6:] == ["USD", "40.00", "USD"]


def test_the_export_round_trips_into_a_new_ledger(client, rich, session):
    exported = client.get("/export").text

    newcomer = service_for(session, NEWCOMER)
    summary = newcomer.run_import(exported)
    assert summary.errors == []
    assert "INFY" in summary.new_commodities, "your own commodities come along"

    again = service_for(session, NEWCOMER).export_ledger()
    strip = lambda text: "\n".join(line for line in text.splitlines() if not line.startswith("; finode export"))  # noqa: E731
    assert strip(again) == strip(exported)

    # and the numbers agree
    mine = service_for(session, TEST_USER_ID).accounts
    theirs = newcomer.accounts
    balance = lambda svc: {a.name: (a.balance, a.commodity) for a in svc.list()}  # noqa: E731
    assert balance(theirs) == balance(mine)
    assert theirs.catalog() and any(c.code == "INFY" and c.user == NEWCOMER for c in theirs.catalog().values())
    infy = next(c for c in theirs.catalog().values() if c.code == "INFY")
    assert (infy.name, infy.kind, infy.decimals) == ("Infosys", "stock", 0)
    assert [(p.commodity, p.price) for p in theirs.prices.list() if not p.is_global] == [("INFY", Decimal("1650.5"))]


# ---- importing ---------------------------------------------------------------------------------------------------


def _import(client, text, **params):
    return client.post("/import", files={"file": ("a.ledger", text.encode())}, params=params)


FOREIGN = """\
commodity 1,000.00 USD
P 2026-01-01 USD 83.5 INR
account Assets:Wise
account Assets:HDFC
2026-01-02 Opening
    Assets:HDFC           100000.00 INR
    Equity:Opening Balances
2026-01-05 Buy USD
    Assets:Wise           100.00 USD @@ 8350.00 INR
    Assets:HDFC
2026-01-06 Buy shares
    Assets:Zerodha:INFY   10 INFY @ 1500 INR
    Assets:HDFC
2026-01-07 Coffee abroad
    Expenses:Food         4.50 USD
    Assets:Wise
"""


def test_import_reads_conversions_prices_and_new_commodities(client):
    response = _import(client, FOREIGN)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["errors"] == [] and body["transactions"] == 4
    assert body["new_commodities"] == ["INFY"]
    assert body["other_commodities"] == ["INFY", "USD"]
    assert body["prices"] == 1
    assert body["assets"] == "76650.00", "only the default-currency accounts count"

    accounts = {a["name"]: a for a in client.get("/accounts/").json()}
    assert accounts["Wise"]["commodity"] == "USD" and accounts["Wise"]["balance"] == "95.50"
    assert accounts["INFY"]["commodity"] == "INFY" and accounts["INFY"]["balance"] == "10.00"
    assert accounts["Zerodha"]["commodity"] == "INR", "a group without postings holds the default currency"
    assert accounts["HDFC"]["commodity"] == "INR" and accounts["HDFC"]["balance"] == "76650.00"
    assert accounts["Food"]["commodity"] == "USD"
    assert accounts["Opening Balances"]["commodity"] == "INR"

    infy = next(c for c in client.get("/commodities/").json() if c["code"] == "INFY")
    assert infy["is_global"] is False and infy["decimals"] == 2 and infy["kind"] == "other"
    rate = client.get("/prices/rate", params={"commodity": "INFY", "quote": "INR"}).json()
    assert Decimal(rate["rate"]) == Decimal("1500"), "the purchase is a price too"

    by_payee = {t["payee"]: t for t in client.get("/transactions/").json()}
    buy = by_payee["Buy USD"]
    assert buy["currency"] == "INR"
    assert {p["amount"]: p["value"] for p in buy["postings"]} == {"100.00": "8350.00", "8350.00": "8350.00"}
    coffee = by_payee["Coffee abroad"]
    assert coffee["currency"] == "USD"
    assert all(p["value"] == p["amount"] == "4.50" for p in coffee["postings"])


def test_a_dry_run_changes_nothing(client):
    body = _import(client, FOREIGN, dry_run="true").json()
    assert body["errors"] == [] and body["new_commodities"] == ["INFY"] and body["prices"] == 1
    assert client.get("/transactions/").json() == []
    assert "INFY" not in {c["code"] for c in client.get("/commodities/").json()}
    assert client.get("/prices/").json() == []


def test_symbols_resolve_to_commodities_and_unlabeled_amounts_to_the_default(client):
    text = """\
2026-01-01 x
    Assets:Bank       ₹1,000.00
    Equity:Opening Balances
2026-01-02 y
    Assets:Cash       500
    Assets:Bank       -500 INR
2026-01-03 z
    Assets:Wallet     $10 @@ ₹830
    Assets:Bank       -₹830
"""
    assert _import(client, text).status_code == 200
    accounts = {a["name"]: a["commodity"] for a in client.get("/accounts/").json()}
    assert accounts["Bank"] == "INR" and accounts["Cash"] == "INR" and accounts["Wallet"] == "USD"


def test_import_declares_decimals_and_kind_from_directives(client):
    text = """\
commodity 1,000.000 NIFTYBEES  ; name:Nifty fund, kind:fund
2026-01-01 Buy
    Assets:Funds:NIFTYBEES   12.345 NIFTYBEES @@ 3000 INR
    Assets:Bank              -3000 INR
"""
    assert _import(client, text).status_code == 200
    fund = next(c for c in client.get("/commodities/").json() if c["code"] == "NIFTYBEES")
    assert (fund["name"], fund["kind"], fund["decimals"]) == ("Nifty fund", "fund", 3)


# ---- what import refuses -------------------------------------------------------------------------------------------


def errors_of(client, text):
    response = _import(client, text)
    assert response.status_code == 400, response.text
    return response.json()["detail"]["errors"]


def test_an_account_cannot_mix_commodities(client):
    text = """\
2026-01-01 a
    Assets:Wise   100 USD
    Equity:Opening Balances  -100 USD
2026-01-02 b
    Assets:Wise   50 EUR
    Equity:Opening Balances  -50 EUR
"""
    errors = errors_of(client, text)
    assert any("'Assets:Wise' mixes EUR and USD, but an account holds one commodity" in e for e in errors)
    assert any("Equity:Opening Balances" in e and "can hold only one commodity" in e for e in errors)
    assert client.get("/transactions/").json() == []


def test_a_transaction_in_two_commodities_needs_a_price(client):
    errors = errors_of(client, "2026-01-01 a\n    Assets:Wise   100 USD\n    Assets:HDFC  -8350 INR\n")
    assert errors[0].startswith("line 1: mixes currencies") and "@@" in errors[0]


def test_conversions_must_share_one_pricing_commodity(client):
    text = (
        "2026-01-01 a\n    Assets:One  10 USD @@ 800 INR\n    Assets:Two  5 EUR @@ 450 GBP\n"
        "    Assets:Three  -800 INR\n    Assets:Four  -450 GBP\n"
    )
    assert "priced in the same commodity" in errors_of(client, text)[0]


def test_a_posting_in_another_commodity_without_a_price_is_explained(client):
    text = (
        "2026-01-01 a\n    Assets:One  10 USD @@ 800 INR\n    Assets:Two  -800 INR\n"
        "    Assets:Three  5 EUR\n    Assets:Four  -5 EUR\n"
    )
    errors = errors_of(client, text)
    assert any("is in EUR but the transaction is in INR" in e and "@@" in e for e in errors)


def test_amounts_respect_each_commodities_decimals(client):
    errors = errors_of(client, "2026-01-01 a\n    Assets:Bank  10.005\n    Equity:Opening Balances  -10.005\n")
    assert errors == ["line 2: '10.005' has more than 2 decimal places, which is what INR allows"]
    errors = errors_of(client, "2026-01-01 a\n    Assets:Coin  3 BTC @ 83.123 USD\n    Assets:Wise  -249.369 USD\n")
    assert errors == [
        "line 2: '249.369' has more than 2 decimal places, which is what USD allows; write the total with '@@'"
    ]
    declared = "commodity 1,000 INFY\n2026-01-01 a\n    Assets:Shares  2.5 INFY @@ 3000 INR\n    Assets:Bank  -3000 INR\n"
    assert "more than 0 decimal places, which is what INFY allows" in errors_of(client, declared)[0]


def test_an_unusable_symbol_is_explained(client):
    errors = errors_of(client, "2026-01-01 a\n    Assets:X  5 ¤\n    Equity:Opening Balances  -5 ¤\n")
    assert "'¤' is not a commodity finode can use" in errors[0]


def test_a_commodity_cannot_be_priced_in_itself(client):
    errors = errors_of(
        client, "P 2026-01-01 USD 1 USD\n2026-01-01 a\n    Assets:Bank  5\n    Equity:Opening Balances\n"
    )
    assert errors == ["line 1: a commodity cannot be priced in itself"]


def test_existing_accounts_keep_what_they_hold(client, root_accounts):
    make(client, "Wise", root_accounts["Assets"], "EUR")
    errors = errors_of(client, "2026-01-01 a\n    Assets:Wise  5 USD\n    Equity:Opening Balances  -5 USD\n")
    assert errors == ["line 2: 'Assets:Wise' holds EUR but the file posts USD to it"]


def test_a_failed_import_saves_no_commodities_or_prices(client):
    bad = FOREIGN + "2026-01-08 oops\n    Expenses:Food  5\n    Assets:HDFC  -4\n"
    assert _import(client, bad).status_code == 400
    assert "INFY" not in {c["code"] for c in client.get("/commodities/").json()}
    assert client.get("/prices/").json() == []
    assert client.get("/transactions/").json() == []


def test_importing_into_a_dollar_ledger_reads_dollars_as_the_default(client):
    client.patch("/profile/", json={"default_currency": "USD"})
    text = "2026-01-01 a\n    Assets:Bank  $100\n    Equity:Opening Balances\n"
    assert _import(client, text).status_code == 200
    accounts = {a["name"]: a for a in client.get("/accounts/").json()}
    assert accounts["Bank"]["commodity"] == "USD"
    assert Decimal(client.get("/reports/summary").json()["net_worth"]) == Decimal("100.00")


def test_a_hundred_dollars_for_a_rupee_ledger_is_valued_after_pricing(client):
    text = "2026-01-01 a\n    Assets:Bank  $100\n    Equity:Opening Balances\n"
    assert _import(client, text).status_code == 200
    summary = client.get("/reports/summary").json()
    assert summary["currency"] == "INR" and summary["unpriced"] is True
