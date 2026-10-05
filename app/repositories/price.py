from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import or_
from sqlmodel import Session, select

from ..models.price import Price


class PriceRepository:
    """Prices the user can see: the shared feed plus the ones they entered."""

    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self, commodity_id: UUID | None = None) -> list[Price]:
        statement = select(Price).where(or_(Price.user.is_(None), Price.user == self.uid))
        if commodity_id is not None:
            statement = statement.where(or_(Price.commodity_id == commodity_id, Price.quote_id == commodity_id))
        return self.db.exec(statement.order_by(Price.date.desc(), Price.created.desc())).all()

    def read(self, pid: UUID) -> Price | None:
        return self.db.exec(
            select(Price).where(Price.pid == pid, or_(Price.user.is_(None), Price.user == self.uid))
        ).first()

    def upsert(self, commodity_id: UUID, quote_id: UUID, on: date, price: Decimal) -> Price:
        """Set the user's own price for a day, replacing the one already entered for it."""
        existing = self.db.exec(
            select(Price).where(
                Price.user == self.uid,
                Price.commodity_id == commodity_id,
                Price.quote_id == quote_id,
                Price.date == on,
            )
        ).first()
        if existing:
            existing.price = price
            self.db.add(existing)
            self.db.flush()
            return existing
        created = Price(user=self.uid, commodity_id=commodity_id, quote_id=quote_id, date=on, price=price)
        self.db.add(created)
        self.db.flush()
        return created

    def delete(self, pid: UUID) -> Price | None:
        """Only the user's own prices can be removed."""
        price = self.db.exec(select(Price).where(Price.pid == pid, Price.user == self.uid)).first()
        if price:
            self.db.delete(price)
            self.db.flush()
        return price
