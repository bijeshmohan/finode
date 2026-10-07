from datetime import date
from decimal import Decimal

from .htmlutil import element, options, text_of


def test_the_profile_offers_the_default_currency(client):
    card = element(client.get("/profile").text, "currency")
    choices = {value: selected for value, selected, _ in options(card)}
    assert choices["INR"] is True and choices["USD"] is False
    assert "BTC" not in choices, "only currencies can be the default"
    assert 'href="/commodities"' in card


def test_the_default_currency_can_be_changed_from_the_profile(client):
    response = client.post("/profile/currency", data={"currency": "USD"})
    assert response.status_code == 200 and response.headers["HX-Redirect"] == "/profile#currency"
    assert client.get("/api/profile/").json()["default_currency"] == "USD"
    card = element(client.get("/profile").text, "currency")
    assert [value for value, selected, _ in options(card) if selected] == ["USD"]


def test_a_bad_currency_is_explained_in_place(client):
    response = client.post("/profile/currency", data={"currency": "BTC"})
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#currency-error"
    assert "not a currency" in response.text
    response = client.post("/profile/currency", data={"currency": ""})
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#currency-error"


def test_the_assets_page_lists_prices_assets_and_currencies(client):
    text = client.get("/commodities").text
    assert "<title>Assets & prices · finode</title>" in text
    assert "None of your accounts hold anything other than INR" in text_of(element(text, "rates"))
    builtin = text[text.index("<details"):]
    assert "INR" in builtin and "Turkish Lira" in builtin and "Bitcoin" not in builtin
    assert "Bitcoin" in text_of(element(text, "mine")), "your own assets are listed with the form to add more"
    assert 'value="currency"' not in text, "you cannot create a currency of your own"


def test_a_price_can_be_added_and_removed(client):
    response = client.post(
        "/commodities/prices", data={"commodity": "USD", "quote": "INR", "price": "83.5", "date": "2026-01-02"}
    )
    assert response.status_code == 200 and response.headers["HX-Redirect"] == "/commodities#prices"
    prices = text_of(element(client.get("/commodities").text, "prices"))
    assert "1 USD" in prices and "83.50 INR" in prices

    pid = client.get("/api/prices/").json()[0]["pid"]
    assert client.post(f"/commodities/prices/{pid}/delete").headers["HX-Redirect"] == "/commodities#prices"
    assert client.get("/api/prices/").json() == []
    assert client.post(f"/commodities/prices/{pid}/delete").status_code == 404


def test_price_errors_are_shown_in_place(client):
    for form, message in (
        ({"commodity": "USD", "quote": "USD", "price": "1"}, "cannot be priced in itself"),
        ({"commodity": "USD", "quote": "INR", "price": "abc"}, "not a valid amount"),
        ({"commodity": "USD", "quote": "INR", "price": "0"}, "greater than 0"),
        ({"commodity": "NOPE", "quote": "INR", "price": "5"}, "unknown commodity"),
        ({"commodity": "USD", "quote": "INR", "price": "5", "date": "not-a-date"}, "Invalid isoformat"),
    ):
        response = client.post("/commodities/prices", data=form)
        assert response.status_code == 400, form
        assert response.headers["HX-Retarget"] == "#price-error"
        assert message in response.text, (form, response.text)


def test_a_commodity_can_be_added_and_removed(client):
    response = client.post(
        "/commodities", data={"code": "infy", "name": "Infosys", "kind": "stock", "decimals": "0", "symbol": ""}
    )
    assert response.headers["HX-Redirect"] == "/commodities#mine"
    mine = text_of(element(client.get("/commodities").text, "mine"))
    assert "INFY" in mine and "Stock, 0 decimals" in mine

    cid = next(c["cid"] for c in client.get("/api/commodities/").json() if c["code"] == "INFY")
    assert client.post(f"/commodities/{cid}/delete").headers["HX-Redirect"] == "/commodities#mine"
    assert client.get("/api/commodities/INFY").status_code == 404


def test_commodity_errors_are_shown_in_place(client):
    for form, message, target in (
        ({"code": "USD", "name": "x"}, "already exists", "#commodity-error"),
        ({"code": "has space", "name": "x"}, "code must be", "#commodity-error"),
        ({"code": "OK", "name": "x", "decimals": "many"}, "not a whole number", "#commodity-error"),
        ({"code": "OK", "name": "x", "decimals": "12"}, "less than or equal to 8", "#commodity-error"),
    ):
        response = client.post("/commodities", data=form)
        assert response.status_code == 400, form
        assert response.headers["HX-Retarget"] == target
        assert message in response.text, (form, response.text)


def test_removing_a_commodity_in_use_is_refused_in_place(client, root_accounts):
    client.post("/api/commodities/", json={"code": "INFY", "name": "Infosys", "decimals": 0})
    client.post("/api/accounts/", json={"name": "Shares", "parent_id": root_accounts["Assets"], "commodity": "INFY"})
    cid = next(c["cid"] for c in client.get("/api/commodities/").json() if c["code"] == "INFY")
    response = client.post(f"/commodities/{cid}/delete")
    assert response.status_code == 400 and response.headers["HX-Retarget"] == "#mine-error"
    assert "in use" in response.text


def test_holdings_without_a_price_are_called_out(client, root_accounts):
    client.post("/api/accounts/", json={"name": "Wise", "parent_id": root_accounts["Assets"], "commodity": "USD"})
    rates = text_of(element(client.get("/commodities").text, "rates"))
    assert "1 USD" in rates and "has no price yet" in rates

    client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "price": "83.5", "date": "2026-01-02"})
    rates = text_of(element(client.get("/commodities").text, "rates"))
    assert "= 83.50 INR" in rates and "no price" not in rates


def test_money_keeps_the_places_of_coins_and_two_for_everything_else():
    from app.templating import money, with_unit

    assert money(Decimal("1234567.5")) == "1,234,567.50"
    assert money(Decimal("0.01234567")) == "0.01234567"
    assert money(Decimal("-5")) == "−5.00"
    assert money(None) == ""
    assert with_unit("1.00", "USD", "INR") == "1.00 USD"
    assert with_unit("1.00", "INR", "INR") == "1.00"
    assert with_unit("1.00", None, "INR") == "1.00"
