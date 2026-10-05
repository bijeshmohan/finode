from uuid import UUID

from sqlalchemy import or_
from sqlmodel import Session, select

from ..commodity_seed import DEFAULT_CURRENCY_CODE
from ..models.commodity import Commodity
from ..models.profile import Profile


class CommodityRepository:
    """Commodities the user can see: the global catalog plus their own."""

    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def _visible(self):
        return select(Commodity).where(or_(Commodity.user.is_(None), Commodity.user == self.uid))

    def list(self) -> list[Commodity]:
        return self.db.exec(self._visible().order_by(Commodity.code)).all()

    def read(self, cid: UUID) -> Commodity | None:
        return self.db.exec(self._visible().where(Commodity.cid == cid)).first()

    def read_by_code(self, code: str) -> Commodity | None:
        matches = self.db.exec(self._visible().where(Commodity.code == code)).all()
        # A private code never repeats a global one, but prefer the user's own if it ever does.
        return next((c for c in matches if c.user is not None), matches[0] if matches else None)

    def create(self, **fields) -> Commodity:
        commodity = Commodity(user=self.uid, **fields)
        self.db.add(commodity)
        self.db.flush()
        return commodity

    def in_use(self, cid: UUID) -> bool:
        """Whether any account, transaction, price or profile refers to the commodity."""
        from ..models.account import Account
        from ..models.price import Price
        from ..models.transaction import Transaction

        checks = (
            select(Account.aid).where(Account.commodity_id == cid),
            select(Transaction.tid).where(Transaction.currency_id == cid),
            select(Price.pid).where(or_(Price.commodity_id == cid, Price.quote_id == cid)),
            select(Profile.user).where(Profile.default_commodity_id == cid),
        )
        return any(self.db.exec(check.limit(1)).first() is not None for check in checks)

    def delete(self, cid: UUID) -> Commodity | None:
        """Only the user's own commodities can be removed."""
        commodity = self.db.exec(select(Commodity).where(Commodity.cid == cid, Commodity.user == self.uid)).first()
        if commodity:
            self.db.delete(commodity)
            self.db.flush()
        return commodity

    def global_by_code(self, code: str) -> Commodity | None:
        return self.db.exec(select(Commodity).where(Commodity.code == code, Commodity.user.is_(None))).first()

    def default_currency(self) -> Commodity:
        """The currency totals are reported in: the profile's choice, otherwise the application default."""
        profile = self.db.exec(select(Profile).where(Profile.user == self.uid)).first()
        if profile and profile.default_commodity_id:
            chosen = self.read(profile.default_commodity_id)
            if chosen:
                return chosen
        fallback = self.global_by_code(DEFAULT_CURRENCY_CODE)
        if fallback is None:
            raise RuntimeError("the global commodity catalog is empty; run 'alembic upgrade head'")
        return fallback
