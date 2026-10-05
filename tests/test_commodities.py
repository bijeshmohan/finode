from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.commodity_seed import SEED_COMMODITIES, seed_id
from app.models.commodity import Commodity
from app.models.utils import normalize_amount
from app.repositories import CommodityRepository

from .conftest import TEST_USER_ID


OTHER_USER = UUID("00000000-0000-4000-8000-000000000002")


# --- the shared catalog ---------------------------------------------------------------


def test_catalog_lists_the_seeded_commodities(client):
    response = client.get("/commodities/")
    assert response.status_code == 200
    by_code = {c["code"]: c for c in response.json()}
    assert {code for code, *_ in SEED_COMMODITIES} == set(by_code)
    assert by_code["INR"] == {
        "cid": str(seed_id("INR")),
        "code": "INR",
        "name": "Indian Rupee",
        "kind": "currency",
        "decimals": 2,
        "symbol": "₹",
        "is_global": True,
    }
    assert by_code["JPY"]["decimals"] == 0
    assert by_code["BTC"]["decimals"] == 8 and by_code["BTC"]["kind"] == "crypto"


def test_a_commodity_can_be_read_by_code(client):
    assert client.get("/commodities/USD").json()["name"] == "US Dollar"
    assert client.get("/commodities/NOPE").status_code == 404


def test_seed_ids_are_stable_and_unique():
    ids = [seed_id(code) for code, *_ in SEED_COMMODITIES]
    assert len(set(ids)) == len(ids)
    assert seed_id("INR") == seed_id("INR")


def test_global_codes_are_unique(session: Session):
    session.add(Commodity(code="INR", name="Duplicate", user=None))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


# --- private commodities ----------------------------------------------------------------


def test_a_user_sees_the_catalog_and_only_their_own_commodities(session: Session):
    session.add(Commodity(code="MYFUND", name="Mine", kind="fund", decimals=3, user=TEST_USER_ID))
    session.add(Commodity(code="THEIRS", name="Theirs", kind="stock", decimals=0, user=OTHER_USER))
    session.commit()

    mine = {c.code for c in CommodityRepository(session, TEST_USER_ID).list()}
    theirs = {c.code for c in CommodityRepository(session, OTHER_USER).list()}

    assert "MYFUND" in mine and "THEIRS" not in mine and "INR" in mine
    assert "THEIRS" in theirs and "MYFUND" not in theirs and "INR" in theirs


def test_private_codes_are_unique_per_user_but_may_repeat_across_users(session: Session):
    session.add(Commodity(code="INFY", name="Infosys", kind="stock", user=TEST_USER_ID))
    session.add(Commodity(code="INFY", name="Someone else's", kind="stock", user=OTHER_USER))
    session.commit()

    session.add(Commodity(code="INFY", name="Again", kind="stock", user=TEST_USER_ID))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_another_users_commodity_cannot_be_read_by_id_or_code(session: Session):
    theirs = Commodity(code="THEIRS", name="Theirs", user=OTHER_USER)
    session.add(theirs)
    session.commit()
    repo = CommodityRepository(session, TEST_USER_ID)
    assert repo.read(theirs.cid) is None
    assert repo.read_by_code("THEIRS") is None


# --- the default currency -----------------------------------------------------------------


def test_the_default_currency_is_inr_for_a_new_user(session: Session):
    assert CommodityRepository(session, uuid4()).default_currency().code == "INR"


def test_the_profile_remembers_the_default_currency_chosen_at_creation(client):
    assert client.get("/profile/").json()["default_currency"] == "INR"


def test_a_missing_catalog_is_reported_clearly(session: Session):
    for commodity in session.exec(select(Commodity)).all():
        session.delete(commodity)
    session.commit()
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        CommodityRepository(session, TEST_USER_ID).default_currency()


# --- amounts keep their two-decimal look ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100", "100.00"),
        ("100.00000000", "100.00"),
        ("0.5", "0.50"),
        ("0.01250000", "0.0125"),
        ("1234.567", "1234.567"),
        ("0E-8", "0.00"),
        ("0.00000001", "0.00000001"),
        ("-12.5", "-12.50"),
        ("1E+2", "100.00"),
    ],
)
def test_normalize_amount(raw, expected):
    assert format(normalize_amount(Decimal(raw)), "f") == expected


def test_amounts_round_trip_with_eight_decimals(session: Session, client, account):
    from app.models.transaction import Posting, PostingSide, Transaction

    session.add(Commodity(code="TST", name="Test coin", kind="crypto", decimals=8, user=TEST_USER_ID))
    session.commit()
    txn = Transaction(user=TEST_USER_ID, currency_id=seed_id("INR"))
    session.add(txn)
    session.flush()
    session.add(
        Posting(
            user=TEST_USER_ID,
            transaction=txn.tid,
            account=UUID(account["aid"]),
            side=PostingSide.DEBIT,
            amount=Decimal("0.01234567"),
            value=Decimal("1234.50"),
        )
    )
    session.commit()
    session.expire_all()
    stored = session.exec(select(Posting).where(Posting.transaction == txn.tid)).one()
    assert stored.amount == Decimal("0.01234567")
    assert str(stored.value) == "1234.50"
