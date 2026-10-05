"""The global commodity catalog: shared by every user, changed only through migrations or scripts."""

from uuid import NAMESPACE_DNS, UUID, uuid5


# (code, name, kind, decimals, symbol)
SEED_COMMODITIES: tuple[tuple[str, str, str, int, str | None], ...] = (
    ("INR", "Indian Rupee", "currency", 2, "₹"),
    ("USD", "US Dollar", "currency", 2, "$"),
    ("EUR", "Euro", "currency", 2, "€"),
    ("GBP", "Pound Sterling", "currency", 2, "£"),
    ("JPY", "Japanese Yen", "currency", 0, "¥"),
    ("AUD", "Australian Dollar", "currency", 2, "A$"),
    ("CAD", "Canadian Dollar", "currency", 2, "C$"),
    ("CHF", "Swiss Franc", "currency", 2, None),
    ("CNY", "Chinese Yuan", "currency", 2, "CN¥"),
    ("HKD", "Hong Kong Dollar", "currency", 2, "HK$"),
    ("SGD", "Singapore Dollar", "currency", 2, "S$"),
    ("AED", "UAE Dirham", "currency", 2, None),
    ("SAR", "Saudi Riyal", "currency", 2, None),
    ("NZD", "New Zealand Dollar", "currency", 2, "NZ$"),
    ("SEK", "Swedish Krona", "currency", 2, None),
    ("NOK", "Norwegian Krone", "currency", 2, None),
    ("DKK", "Danish Krone", "currency", 2, None),
    ("ZAR", "South African Rand", "currency", 2, None),
    ("BTC", "Bitcoin", "crypto", 8, "₿"),
    ("ETH", "Ether", "crypto", 8, "Ξ"),
    ("USDT", "Tether", "crypto", 6, None),
    ("USDC", "USD Coin", "crypto", 6, None),
)

DEFAULT_CURRENCY_CODE = "INR"


def seed_id(code: str) -> UUID:
    """Global commodities have the same id in every database."""
    return uuid5(NAMESPACE_DNS, f"{code}.commodities.finode")


def seed_rows(now) -> list[dict]:
    return [
        {
            "cid": seed_id(code),
            "user": None,
            "code": code,
            "name": name,
            "kind": kind,
            "decimals": decimals,
            "symbol": symbol,
            "created": now,
            "updated": now,
        }
        for code, name, kind, decimals, symbol in SEED_COMMODITIES
    ]
