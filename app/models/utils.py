from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, event, inspect
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field, Session, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


def without_nul(text: str) -> str:
    """A NUL character (U+0000) cannot be stored or searched for in Postgres text: it answers with an error."""
    return text.replace("\x00", "")


@event.listens_for(Session, "before_flush")
def _strip_nul_characters(session: Session, flush_context, instances) -> None:
    """Whatever is written (a payee, a note, an account name, from the web, the API or an assistant), a NUL is dropped
    first, so it can never turn into a server error."""
    for obj in (*session.new, *session.dirty):
        for column in inspect(obj).mapper.column_attrs:
            value = getattr(obj, column.key, None)
            if isinstance(value, str) and "\x00" in value:
                setattr(obj, column.key, without_nul(value))


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
    """Exact amount of money: up to eight decimals, read back without padding zeros."""

    impl = Numeric
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(24, 8)

    def process_result_value(self, value, dialect):
        return None if value is None else normalize_amount(value)
