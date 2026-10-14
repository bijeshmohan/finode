from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.services.prices import RANK_MANUAL, RANK_TRANSACTION, PriceBook, PricePoint


INR, USD, BTC, INFY, EUR = (uuid4() for _ in range(5))


def d(day: int) -> date:
    return date(2026, 1, day)


def point(commodity, quote, day, price, rank=RANK_TRANSACTION, seq=0.0):
    return PricePoint(commodity, quote, d(day), Decimal(price), rank, seq)


def test_same_commodity_is_worth_itself():
    assert PriceBook([]).rate(INR, INR, d(1)).value == 1


def test_nothing_is_known_without_prices():
    assert PriceBook([]).rate(USD, INR, d(1)) is None
    assert PriceBook([point(USD, INR, 1, "80")]).rate(EUR, INR, d(5)) is None


def test_direct_price_uses_the_latest_on_or_before_the_day():
    book = PriceBook([point(USD, INR, 1, "80"), point(USD, INR, 10, "84"), point(USD, INR, 20, "90")])
    assert book.rate(USD, INR, d(1)).value == 80
    assert book.rate(USD, INR, d(9)).value == 80
    assert book.rate(USD, INR, d(10)).value == 84
    assert book.rate(USD, INR, d(25)).value == 90
    assert book.rate(USD, INR, d(25)).as_of == d(20)


def test_a_price_from_the_future_is_not_used():
    assert PriceBook([point(USD, INR, 10, "84")]).rate(USD, INR, d(9)) is None


def test_inverse_price():
    book = PriceBook([point(USD, INR, 1, "80")])
    assert book.rate(INR, USD, d(1)).value == Decimal("0.0125")
    assert book.convert(Decimal("8000"), INR, USD, d(1)) == Decimal("100")


def test_the_most_recent_of_direct_and_inverse_wins():
    book = PriceBook([point(USD, INR, 1, "80"), point(INR, USD, 5, "0.01")])
    assert book.rate(USD, INR, d(6)).value == 100
    assert book.rate(USD, INR, d(3)).value == 80


def test_one_hop_through_a_common_commodity():
    book = PriceBook([point(INFY, INR, 1, "1500"), point(USD, INR, 1, "80")])
    assert book.rate(INFY, USD, d(1)).value == Decimal("18.75")
    assert book.rate(USD, INFY, d(1)).value.quantize(Decimal("0.000001")) == Decimal("0.053333")


def test_a_hop_prefers_the_freshest_route():
    book = PriceBook(
        [
            point(BTC, INR, 1, "100"),
            point(BTC, EUR, 9, "1"),
            point(INR, EUR, 1, "0.5"),
            point(USD, EUR, 9, "2"),
            point(USD, INR, 1, "80"),
        ]
    )
    # BTC -> USD can go through INR (days 1 and 1) or EUR (days 9 and 9).
    rate = book.rate(BTC, USD, d(10))
    assert rate.as_of == d(9) and rate.value == Decimal("0.5")


def test_two_hops_are_not_attempted():
    # INFY -> INR -> USD -> EUR is three links: too indirect to trust.
    book = PriceBook([point(INFY, INR, 1, "1500"), point(USD, INR, 1, "80"), point(USD, EUR, 1, "1")])
    assert book.rate(INFY, EUR, d(1)) is None


def test_ties_on_one_day_prefer_the_users_own_price_over_a_conversion():
    day = [point(USD, INR, 5, "82", RANK_TRANSACTION), point(USD, INR, 5, "83", RANK_MANUAL)]
    assert PriceBook(day).rate(USD, INR, d(5)).value == 83
    assert PriceBook(day[:1]).rate(USD, INR, d(5)).value == 82


def test_among_equal_ranks_the_latest_entry_wins():
    book = PriceBook([point(USD, INR, 5, "81", seq=1.0), point(USD, INR, 5, "82", seq=2.0)])
    assert book.rate(USD, INR, d(5)).value == 82


def test_a_newer_conversion_rate_beats_an_older_manual_price():
    book = PriceBook([point(USD, INR, 1, "80", RANK_MANUAL), point(USD, INR, 8, "85", RANK_TRANSACTION)])
    assert book.rate(USD, INR, d(9)).value == 85


def test_convert_rounds_half_up_to_the_requested_decimals():
    book = PriceBook([point(USD, INR, 1, "83.335")])
    assert book.convert(Decimal("1"), USD, INR, d(1), decimals=2) == Decimal("83.34")
    assert book.convert(Decimal("1"), USD, INR, d(1), decimals=0) == Decimal("83")
    assert book.convert(Decimal("3"), USD, INR, d(1)) == Decimal("250.005")


def test_convert_returns_none_when_unpriced():
    assert PriceBook([]).convert(Decimal("1"), BTC, INR, d(1)) is None
