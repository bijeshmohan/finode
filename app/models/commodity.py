from uuid import UUID, uuid4

from sqlalchemy import Index, text
from sqlmodel import Field

from .utils import TimestampMixin


class CommodityKind:
    CURRENCY = "currency"
    CRYPTO = "crypto"
    STOCK = "stock"
    FUND = "fund"
    OTHER = "other"

    ALL = (CURRENCY, CRYPTO, STOCK, FUND, OTHER)


class Commodity(TimestampMixin, table=True):
    """Anything an account can hold a quantity of: a currency, a coin, a share, a fund.

    Rows with no `user` are the built-in currencies (ISO 4217), the same for everybody and
    changed only through migrations; every other commodity is private to one user. A code is
    unique among the built-in currencies and within one user's own rows.
    """

    __tablename__ = "commodities"
    __table_args__ = (
        Index(
            "uq_commodities_global_code",
            "code",
            unique=True,
            sqlite_where=text('"user" IS NULL'),
            postgresql_where=text('"user" IS NULL'),
        ),
        Index(
            "uq_commodities_user_code",
            "user",
            "code",
            unique=True,
            sqlite_where=text('"user" IS NOT NULL'),
            postgresql_where=text('"user" IS NOT NULL'),
        ),
    )

    cid: UUID = Field(default_factory=uuid4, primary_key=True)
    user: UUID | None = Field(default=None, index=True, foreign_key="auth.users.id", nullable=True)
    code: str = Field(max_length=20)
    name: str = Field(max_length=80)
    kind: str = Field(default=CommodityKind.CURRENCY, max_length=10)
    # How many decimals a quantity of this commodity may have (INR 2, JPY 0, BTC 8).
    decimals: int = Field(default=2)
    symbol: str | None = Field(default=None, max_length=8)
