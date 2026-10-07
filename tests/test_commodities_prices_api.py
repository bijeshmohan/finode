from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlmodel import Session

from app.commodity_seed import seed_id
from app.models.commodity import Commodity
from app.models.price import Price
from app.repositories import CommodityRepository, PriceRepository
from app.services.prices import PriceService

from .conftest import TEST_USER_ID


OTHER_USER = UUID("00000000-0000-4000-8000-000000000002")
TODAY = date.today()


# ---- commodities ---------------------------------------------------------------------------


def test_a_user_can_add_a_commodity_of_their_own(client):
    response = client.post("/api/commodities/", json={"code": "infy", "name": "Infosys", "kind": "stock", "decimals": 0})
    assert response.status_code == 201
    assert response.json() | {"cid": None} == {
        "cid": None,
        "code": "INFY",
        "name": "Infosys",
        "kind": "stock",
        "decimals": 0,
        "symbol": None,
    }
    assert "INFY" in {c["code"] for c in client.get("/api/commodities/").json()}


def test_a_built_in_currency_code_cannot_be_reused(client):
    response = client.post("/api/commodities/", json={"code": "usd", "name": "My dollars"})
    assert response.status_code == 400 and "already exists" in response.json()["detail"]


def test_your_own_currencies_cannot_be_created(client):
    response = client.post("/api/commodities/", json={"code": "XYZ", "name": "Mine", "kind": "currency"})
    assert response.status_code == 422 and "built in" in response.text


def test_a_code_of_your_own_cannot_be_reused(client):
    client.post("/api/commodities/", json={"code": "INFY", "name": "Infosys"})
    assert client.post("/api/commodities/", json={"code": "INFY", "name": "Again"}).status_code == 400


def test_commodity_input_is_validated(client):
    for body in (
        {"code": "has space", "name": "x"},
        {"code": "", "name": "x"},
        {"code": "OK", "name": "  "},
        {"code": "OK", "name": "x", "kind": "spaceship"},
        {"code": "OK", "name": "x", "decimals": 9},
        {"code": "OK", "name": "x", "decimals": -1},
    ):
        assert client.post("/api/commodities/", json=body).status_code == 422, body


def test_an_unused_asset_can_be_removed_but_not_a_currency(client):
    created = client.post("/api/commodities/", json={"code": "TMP", "name": "Temporary"}).json()
    assert client.delete(f"/api/commodities/{created['cid']}").status_code == 204
    assert client.get("/api/commodities/TMP").status_code == 404

    refused = client.delete(f"/api/commodities/{seed_id('INR')}")
    assert refused.status_code == 400 and "built-in currency" in refused.json()["detail"]
    assert client.delete(f"/api/commodities/{UUID(int=5)}").status_code == 404


def test_a_commodity_in_use_cannot_be_removed(client, root_accounts):
    created = client.post("/api/commodities/", json={"code": "INFY", "name": "Infosys", "decimals": 0}).json()
    client.post("/api/accounts/", json={"name": "Shares", "parent_id": root_accounts["Assets"], "commodity": "INFY"})
    response = client.delete(f"/api/commodities/{created['cid']}")
    assert response.status_code == 400 and "in use" in response.json()["detail"]


def test_a_commodity_priced_somewhere_cannot_be_removed(client):
    created = client.post("/api/commodities/", json={"code": "INFY", "name": "Infosys", "decimals": 0}).json()
    client.post("/api/prices/", json={"commodity": "INFY", "quote": "INR", "price": "1500"})
    assert client.delete(f"/api/commodities/{created['cid']}").status_code == 400


def test_nobody_can_remove_another_users_commodity(session: Session, client):
    theirs = Commodity(code="THEIRS", name="Theirs", user=OTHER_USER)
    session.add(theirs)
    session.commit()
    assert client.delete(f"/api/commodities/{theirs.cid}").status_code == 404
    assert session.get(Commodity, theirs.cid) is not None


# ---- prices -----------------------------------------------------------------------------------------


def test_setting_a_price_replaces_the_one_for_the_same_day(client):
    first = client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "date": str(TODAY), "price": "83"})
    second = client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "date": str(TODAY), "price": "84.25"})
    assert first.status_code == second.status_code == 201
    assert first.json()["pid"] == second.json()["pid"]
    listed = client.get("/api/prices/", params={"commodity": "USD"}).json()
    assert [Decimal(p["price"]) for p in listed] == [Decimal("84.25")]


def test_prices_are_listed_newest_first_and_filtered(client):
    for days, price in ((10, "80"), (0, "84"), (5, "82")):
        client.post(
            "/api/prices/",
            json={"commodity": "USD", "quote": "INR", "date": str(TODAY - timedelta(days=days)), "price": price},
        )
    client.post("/api/prices/", json={"commodity": "EUR", "quote": "INR", "price": "90"})
    usd = client.get("/api/prices/", params={"commodity": "USD"}).json()
    assert [Decimal(p["price"]) for p in usd] == [Decimal("84"), Decimal("82"), Decimal("80")]
    assert {p["commodity"] for p in client.get("/api/prices/").json()} == {"USD", "EUR"}
    assert client.get("/api/prices/", params={"commodity": "NOPE"}).status_code == 404


def test_price_input_is_validated(client):
    assert client.post("/api/prices/", json={"commodity": "USD", "quote": "USD", "price": "1"}).status_code == 400
    assert client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "price": "0"}).status_code == 422
    assert client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "price": "-3"}).status_code == 422
    assert client.post("/api/prices/", json={"commodity": "NOPE", "quote": "INR", "price": "3"}).status_code == 404


def test_rate_lookup_by_day(client):
    for days, price in ((10, "80"), (2, "84")):
        client.post(
            "/api/prices/",
            json={"commodity": "USD", "quote": "INR", "date": str(TODAY - timedelta(days=days)), "price": price},
        )
    day = lambda days: str(TODAY - timedelta(days=days))  # noqa: E731
    params = {"commodity": "USD", "quote": "INR"}
    assert Decimal(client.get("/api/prices/rate", params=params | {"on": day(5)}).json()["rate"]) == 80
    assert Decimal(client.get("/api/prices/rate", params=params | {"on": day(1)}).json()["rate"]) == 84
    assert client.get("/api/prices/rate", params=params | {"on": day(20)}).json()["rate"] is None
    assert client.get("/api/prices/rate", params={"commodity": "USD", "quote": "NOPE"}).status_code == 404


def test_one_hop_rates_through_a_common_commodity(client):
    client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "price": "80"})
    client.post("/api/prices/", json={"commodity": "EUR", "quote": "INR", "price": "90"})
    rate = client.get("/api/prices/rate", params={"commodity": "EUR", "quote": "USD"}).json()
    assert Decimal(rate["rate"]) == Decimal("1.125")


def test_a_price_can_be_deleted_by_its_owner_only(session: Session, client):
    mine = client.post("/api/prices/", json={"commodity": "USD", "quote": "INR", "price": "80"}).json()
    theirs = Price(
        user=OTHER_USER, commodity_id=seed_id("EUR"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("90")
    )
    session.add(theirs)
    session.commit()

    assert client.delete(f"/api/prices/{theirs.pid}").status_code == 404
    assert client.delete(f"/api/prices/{mine['pid']}").status_code == 204
    assert client.delete(f"/api/prices/{mine['pid']}").status_code == 404










def test_services_of_two_users_do_not_share_prices(session: Session):
    mine = PriceService(PriceRepository(session, TEST_USER_ID), None, CommodityRepository(session, TEST_USER_ID))
    theirs = PriceService(PriceRepository(session, OTHER_USER), None, CommodityRepository(session, OTHER_USER))
    from app.schemas.price import PriceCreate

    mine.set(PriceCreate(commodity="USD", quote="INR", price=Decimal("80")))
    assert [p.price for p in mine.list()] == [Decimal("80")]
    assert theirs.list() == []


def test_prices_read_back_without_padding_zeros(client):
    stored = client.post("/api/prices/", json={"commodity": "BTC", "quote": "INR", "price": "6000000"}).json()
    assert stored["price"] == "6000000.00"
    assert client.get("/api/prices/").json()[0]["price"] == "6000000.00"
    client.post("/api/prices/", json={"commodity": "JPY", "quote": "INR", "date": "2026-01-01", "price": "0.5625"})
    assert next(p for p in client.get("/api/prices/").json() if p["commodity"] == "JPY")["price"] == "0.5625"


def test_another_users_prices_are_not_visible(session: Session, client):
    session.add(Price(user=OTHER_USER, commodity_id=seed_id("EUR"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("90")))
    session.commit()
    assert client.get("/api/prices/").json() == []
    assert client.get("/api/prices/rate", params={"commodity": "EUR", "quote": "INR"}).json()["rate"] is None


def test_a_price_needs_an_owner(session: Session):
    from sqlalchemy.exc import IntegrityError

    session.add(Price(user=None, commodity_id=seed_id("GBP"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("100")))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
