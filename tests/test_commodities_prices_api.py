from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

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
    response = client.post("/commodities/", json={"code": "infy", "name": "Infosys", "kind": "stock", "decimals": 0})
    assert response.status_code == 201
    assert response.json() | {"cid": None} == {
        "cid": None,
        "code": "INFY",
        "name": "Infosys",
        "kind": "stock",
        "decimals": 0,
        "symbol": None,
        "is_global": False,
    }
    assert "INFY" in {c["code"] for c in client.get("/commodities/").json()}


def test_a_code_in_the_catalog_cannot_be_reused(client):
    response = client.post("/commodities/", json={"code": "usd", "name": "My dollars"})
    assert response.status_code == 400 and "already exists" in response.json()["detail"]


def test_a_code_of_your_own_cannot_be_reused(client):
    client.post("/commodities/", json={"code": "INFY", "name": "Infosys"})
    assert client.post("/commodities/", json={"code": "INFY", "name": "Again"}).status_code == 400


def test_commodity_input_is_validated(client):
    for body in (
        {"code": "has space", "name": "x"},
        {"code": "", "name": "x"},
        {"code": "OK", "name": "  "},
        {"code": "OK", "name": "x", "kind": "spaceship"},
        {"code": "OK", "name": "x", "decimals": 9},
        {"code": "OK", "name": "x", "decimals": -1},
    ):
        assert client.post("/commodities/", json=body).status_code == 422, body


def test_an_unused_commodity_can_be_removed_but_not_the_catalog(client):
    created = client.post("/commodities/", json={"code": "TMP", "name": "Temporary"}).json()
    assert client.delete(f"/commodities/{created['cid']}").status_code == 204
    assert client.get("/commodities/TMP").status_code == 404

    refused = client.delete(f"/commodities/{seed_id('INR')}")
    assert refused.status_code == 400 and "shared catalog" in refused.json()["detail"]
    assert client.delete(f"/commodities/{UUID(int=5)}").status_code == 404


def test_a_commodity_in_use_cannot_be_removed(client, root_accounts):
    created = client.post("/commodities/", json={"code": "INFY", "name": "Infosys", "decimals": 0}).json()
    client.post("/accounts/", json={"name": "Shares", "parent_id": root_accounts["Assets"], "commodity": "INFY"})
    response = client.delete(f"/commodities/{created['cid']}")
    assert response.status_code == 400 and "in use" in response.json()["detail"]


def test_a_commodity_priced_somewhere_cannot_be_removed(client):
    created = client.post("/commodities/", json={"code": "INFY", "name": "Infosys", "decimals": 0}).json()
    client.post("/prices/", json={"commodity": "INFY", "quote": "INR", "price": "1500"})
    assert client.delete(f"/commodities/{created['cid']}").status_code == 400


def test_nobody_can_remove_another_users_commodity(session: Session, client):
    theirs = Commodity(code="THEIRS", name="Theirs", user=OTHER_USER)
    session.add(theirs)
    session.commit()
    assert client.delete(f"/commodities/{theirs.cid}").status_code == 404
    assert session.get(Commodity, theirs.cid) is not None


# ---- prices -----------------------------------------------------------------------------------------


def test_setting_a_price_replaces_the_one_for_the_same_day(client):
    first = client.post("/prices/", json={"commodity": "USD", "quote": "INR", "date": str(TODAY), "price": "83"})
    second = client.post("/prices/", json={"commodity": "USD", "quote": "INR", "date": str(TODAY), "price": "84.25"})
    assert first.status_code == second.status_code == 201
    assert first.json()["pid"] == second.json()["pid"]
    listed = client.get("/prices/", params={"commodity": "USD"}).json()
    assert [Decimal(p["price"]) for p in listed] == [Decimal("84.25")]
    assert listed[0]["is_global"] is False


def test_prices_are_listed_newest_first_and_filtered(client):
    for days, price in ((10, "80"), (0, "84"), (5, "82")):
        client.post(
            "/prices/",
            json={"commodity": "USD", "quote": "INR", "date": str(TODAY - timedelta(days=days)), "price": price},
        )
    client.post("/prices/", json={"commodity": "EUR", "quote": "INR", "price": "90"})
    usd = client.get("/prices/", params={"commodity": "USD"}).json()
    assert [Decimal(p["price"]) for p in usd] == [Decimal("84"), Decimal("82"), Decimal("80")]
    assert {p["commodity"] for p in client.get("/prices/").json()} == {"USD", "EUR"}
    assert client.get("/prices/", params={"commodity": "NOPE"}).status_code == 404


def test_price_input_is_validated(client):
    assert client.post("/prices/", json={"commodity": "USD", "quote": "USD", "price": "1"}).status_code == 400
    assert client.post("/prices/", json={"commodity": "USD", "quote": "INR", "price": "0"}).status_code == 422
    assert client.post("/prices/", json={"commodity": "USD", "quote": "INR", "price": "-3"}).status_code == 422
    assert client.post("/prices/", json={"commodity": "NOPE", "quote": "INR", "price": "3"}).status_code == 404


def test_rate_lookup_by_day(client):
    for days, price in ((10, "80"), (2, "84")):
        client.post(
            "/prices/",
            json={"commodity": "USD", "quote": "INR", "date": str(TODAY - timedelta(days=days)), "price": price},
        )
    day = lambda days: str(TODAY - timedelta(days=days))  # noqa: E731
    params = {"commodity": "USD", "quote": "INR"}
    assert Decimal(client.get("/prices/rate", params=params | {"on": day(5)}).json()["rate"]) == 80
    assert Decimal(client.get("/prices/rate", params=params | {"on": day(1)}).json()["rate"]) == 84
    assert client.get("/prices/rate", params=params | {"on": day(20)}).json()["rate"] is None
    assert client.get("/prices/rate", params={"commodity": "USD", "quote": "NOPE"}).status_code == 404


def test_one_hop_rates_through_a_common_commodity(client):
    client.post("/prices/", json={"commodity": "USD", "quote": "INR", "price": "80"})
    client.post("/prices/", json={"commodity": "EUR", "quote": "INR", "price": "90"})
    rate = client.get("/prices/rate", params={"commodity": "EUR", "quote": "USD"}).json()
    assert Decimal(rate["rate"]) == Decimal("1.125")


def test_a_price_can_be_deleted_by_its_owner_only(session: Session, client):
    mine = client.post("/prices/", json={"commodity": "USD", "quote": "INR", "price": "80"}).json()
    theirs = Price(
        user=OTHER_USER, commodity_id=seed_id("EUR"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("90")
    )
    feed = Price(user=None, commodity_id=seed_id("GBP"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("100"))
    session.add_all([theirs, feed])
    session.commit()

    assert client.delete(f"/prices/{theirs.pid}").status_code == 404
    assert client.delete(f"/prices/{feed.pid}").status_code == 404, "the shared feed is not the user's to remove"
    assert client.delete(f"/prices/{mine['pid']}").status_code == 204
    assert client.delete(f"/prices/{mine['pid']}").status_code == 404


def test_the_shared_feed_is_visible_but_another_users_prices_are_not(session: Session, client):
    session.add_all(
        [
            Price(commodity_id=seed_id("GBP"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("100")),
            Price(user=OTHER_USER, commodity_id=seed_id("EUR"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("90")),
        ]
    )
    session.commit()
    listed = {(p["commodity"], p["is_global"]) for p in client.get("/prices/").json()}
    assert listed == {("GBP", True)}
    assert Decimal(client.get("/prices/rate", params={"commodity": "GBP", "quote": "INR"}).json()["rate"]) == 100
    assert client.get("/prices/rate", params={"commodity": "EUR", "quote": "INR"}).json()["rate"] is None


def test_your_own_price_beats_the_shared_feed_for_the_same_day(session: Session, client):
    session.add(Price(commodity_id=seed_id("GBP"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("100")))
    session.commit()
    client.post("/prices/", json={"commodity": "GBP", "quote": "INR", "price": "105"})
    assert Decimal(client.get("/prices/rate", params={"commodity": "GBP", "quote": "INR"}).json()["rate"]) == 105


def test_a_newer_feed_price_beats_your_older_one(session: Session, client):
    client.post(
        "/prices/",
        json={"commodity": "GBP", "quote": "INR", "date": str(TODAY - timedelta(days=5)), "price": "105"},
    )
    session.add(Price(commodity_id=seed_id("GBP"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("100")))
    session.commit()
    assert Decimal(client.get("/prices/rate", params={"commodity": "GBP", "quote": "INR"}).json()["rate"]) == 100


def test_feed_prices_are_unique_per_day(session: Session):
    from sqlalchemy.exc import IntegrityError

    row = dict(commodity_id=seed_id("GBP"), quote_id=seed_id("INR"), date=TODAY, price=Decimal("100"))
    session.add(Price(**row))
    session.commit()
    session.add(Price(**row))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
    else:
        raise AssertionError("expected a unique violation")


def test_services_of_two_users_do_not_share_prices(session: Session):
    mine = PriceService(PriceRepository(session, TEST_USER_ID), None, CommodityRepository(session, TEST_USER_ID))
    theirs = PriceService(PriceRepository(session, OTHER_USER), None, CommodityRepository(session, OTHER_USER))
    from app.schemas.price import PriceCreate

    mine.set(PriceCreate(commodity="USD", quote="INR", price=Decimal("80")))
    assert [p.price for p in mine.list()] == [Decimal("80")]
    assert theirs.list() == []
