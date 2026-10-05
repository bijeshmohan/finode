from datetime import date as Date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Index, Numeric, text
from sqlmodel import Field

from .utils import TimestampMixin


class Price(TimestampMixin, table=True):
    """What one unit of `commodity` was worth in `quote` on a date.

    Rows with no `user` are the shared price feed; rows with a user are that user's own,
    entered by hand, and win over the feed. Rates implied by the user's own conversion
    transactions are not stored: they are derived from the postings when needed.
    """

    __tablename__ = "prices"
    __table_args__ = (
        CheckConstraint("price > 0", name="ck_prices_positive"),
        Index(
            "uq_prices_global",
            "commodity_id",
            "quote_id",
            "date",
            unique=True,
            sqlite_where=text('"user" IS NULL'),
            postgresql_where=text('"user" IS NULL'),
        ),
        Index(
            "uq_prices_user",
            "user",
            "commodity_id",
            "quote_id",
            "date",
            unique=True,
            sqlite_where=text('"user" IS NOT NULL'),
            postgresql_where=text('"user" IS NOT NULL'),
        ),
    )

    pid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID | None = Field(default=None, index=True, foreign_key="auth.users.id", nullable=True)
    commodity_id: UUID = Field(foreign_key="commodities.cid")
    quote_id: UUID = Field(foreign_key="commodities.cid")
    date: Date
    price: Decimal = Field(sa_type=Numeric(28, 12))
