from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from ..models.utils import normalize_amount
from ..repositories import CommodityRepository, PriceRepository, TransactionRepository
from ..schemas.price import PriceCreate, PriceRead, RateRead


# Who said it, when two prices are for the same day: the user's own entry, then a rate from
# their own conversion transactions, then the shared feed.
RANK_FEED = 1
RANK_TRANSACTION = 2
RANK_MANUAL = 3


@dataclass(frozen=True)
class PricePoint:
    """One unit of `commodity` was worth `price` of `quote` on `on`."""

    commodity: UUID
    quote: UUID
    on: date
    price: Decimal
    rank: int = RANK_FEED
    seq: float = 0.0


@dataclass(frozen=True)
class Rate:
    value: Decimal
    # The oldest day any price behind this rate is from.
    as_of: date


class PriceBook:
    """Looks up exchange rates between commodities from a set of price points.

    A rate comes from the latest price on or before the day, used directly or inverted.
    When two commodities were never priced against each other, it goes through one
    commodity both were priced against (INFY -> INR -> USD).
    """

    def __init__(self, points: list[PricePoint]):
        by_pair: dict[tuple[UUID, UUID], list[PricePoint]] = {}
        for point in points:
            by_pair.setdefault((point.commodity, point.quote), []).append(point)
        self._dates: dict[tuple[UUID, UUID], list[date]] = {}
        self._points: dict[tuple[UUID, UUID], list[PricePoint]] = {}
        self._neighbours: dict[UUID, set[UUID]] = {}
        for pair, items in by_pair.items():
            items.sort(key=lambda p: (p.on, p.rank, p.seq))
            self._points[pair] = items
            self._dates[pair] = [p.on for p in items]
            self._neighbours.setdefault(pair[0], set()).add(pair[1])
            self._neighbours.setdefault(pair[1], set()).add(pair[0])

    def _latest(self, base: UUID, quote: UUID, asof: date) -> PricePoint | None:
        dates = self._dates.get((base, quote))
        if not dates:
            return None
        index = bisect_right(dates, asof)
        return self._points[(base, quote)][index - 1] if index else None

    def _edge(self, base: UUID, target: UUID, asof: date) -> tuple[Rate, tuple] | None:
        """The latest direct or inverted price between two commodities, with its sort key."""
        direct = self._latest(base, target, asof)
        inverse = self._latest(target, base, asof)
        options = []
        if direct:
            options.append(((direct.on, direct.rank, direct.seq, 1), Rate(direct.price, direct.on)))
        if inverse:
            options.append(((inverse.on, inverse.rank, inverse.seq, 0), Rate(Decimal(1) / inverse.price, inverse.on)))
        if not options:
            return None
        key, rate = max(options, key=lambda o: o[0])
        return rate, key

    def rate(self, base: UUID, target: UUID, asof: date) -> Rate | None:
        """How many `target` one `base` is worth on `asof`, or None if no price links them."""
        if base == target:
            return Rate(Decimal(1), asof)
        edge = self._edge(base, target, asof)
        if edge:
            return edge[0]
        best: Rate | None = None
        for middle in sorted(self._neighbours.get(base, set()) & self._neighbours.get(target, set()), key=str):
            first, second = self._edge(base, middle, asof), self._edge(middle, target, asof)
            if first and second:
                oldest = min(first[0].as_of, second[0].as_of)
                if best is None or oldest > best.as_of:
                    best = Rate(first[0].value * second[0].value, oldest)
        return best

    def convert(
        self, amount: Decimal, base: UUID, target: UUID, asof: date, decimals: int | None = None
    ) -> Decimal | None:
        rate = self.rate(base, target, asof)
        if rate is None:
            return None
        converted = amount * rate.value
        if decimals is not None:
            converted = converted.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
        return converted


class PriceService:
    def __init__(self, pr: PriceRepository, tr: TransactionRepository, cr: CommodityRepository | None = None):
        self.pr = pr
        self.tr = tr
        self.cr = cr or CommodityRepository(pr.db, pr.uid)
        self._book: PriceBook | None = None

    def invalidate(self) -> None:
        self._book = None

    def book(self) -> PriceBook:
        """Every price the user can see, and the rates their own conversions implied."""
        if self._book is None:
            points = [
                PricePoint(
                    p.commodity_id,
                    p.quote_id,
                    p.date,
                    p.price,
                    RANK_MANUAL if p.user is not None else RANK_FEED,
                    p.created.timestamp(),
                )
                for p in self.pr.list()
            ]
            for commodity, currency, on, amount, value, created in self.tr.conversions():
                if amount:
                    points.append(
                        PricePoint(commodity, currency, on, Decimal(value) / Decimal(amount), RANK_TRANSACTION, created.timestamp())
                    )
            self._book = PriceBook(points)
        return self._book

    def _commodity(self, code: str):
        commodity = self.cr.read_by_code(code.strip().upper())
        if commodity is None:
            raise LookupError(f"unknown commodity '{code}'!")
        return commodity

    def _to_read(self, price, codes: dict[UUID, str]) -> PriceRead:
        return PriceRead(
            pid=price.pid,
            commodity=codes[price.commodity_id],
            quote=codes[price.quote_id],
            date=price.date,
            price=normalize_amount(price.price),
            is_global=price.user is None,
        )

    def list(self, code: str | None = None) -> list[PriceRead]:
        """Prices the user can see (the shared feed and their own); rates from their transactions are not listed."""
        codes = {c.cid: c.code for c in self.cr.list()}
        commodity = self._commodity(code) if code else None
        return [self._to_read(p, codes) for p in self.pr.list(commodity.cid if commodity else None)]

    def set(self, data: PriceCreate) -> PriceRead:
        base, quote = self._commodity(data.commodity), self._commodity(data.quote)
        if base.cid == quote.cid:
            raise ValueError("a commodity cannot be priced in itself!")
        price = self.pr.upsert(base.cid, quote.cid, data.date, data.price)
        self.pr.db.commit()
        self.pr.db.refresh(price)
        self.invalidate()
        return self._to_read(price, {c.cid: c.code for c in self.cr.list()})

    def delete(self, pid: UUID) -> None:
        if self.pr.delete(pid) is None:
            raise LookupError("price not found")
        self.pr.db.commit()
        self.invalidate()

    def rate(self, code: str, quote: str, on: date) -> RateRead:
        base, target = self._commodity(code), self._commodity(quote)
        found = self.book().rate(base.cid, target.cid, on)
        return RateRead(
            commodity=base.code,
            quote=target.code,
            date=on,
            rate=found.value if found else None,
            as_of=found.as_of if found else None,
        )
