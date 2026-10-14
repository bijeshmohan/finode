from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Numeric
from sqlalchemy.types import TypeDecorator
from sqlmodel import SQLModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin(SQLModel):
    created: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
    )
    updated: datetime = Field(
        default_factory=utc_now,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": utc_now},
    )


MIN_PLACES = 2


def normalize_amount(value: Decimal | int | str) -> Decimal:
    """Drop the padding zeros beyond two decimals: 100.00000000 -> 100.00, 0.01250000 -> 0.0125.

    The column keeps eight decimals for crypto and fractional shares, but amounts of
    ordinary currencies must keep reading back as plain two-decimal values.
    """
    value = Decimal(value)
    exponent = value.normalize().as_tuple().exponent
    places = max(MIN_PLACES, -exponent) if isinstance(exponent, int) else MIN_PLACES
    return value.quantize(Decimal(1).scaleb(-places))


class Amount(TypeDecorator):
    """Exact quantity of a commodity: up to eight decimals, read back without padding zeros."""

    impl = Numeric
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(24, 8)

    def process_result_value(self, value, dialect):
        return None if value is None else normalize_amount(value)
