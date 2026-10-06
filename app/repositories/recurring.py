from datetime import date
from uuid import UUID

from sqlalchemy import or_
from sqlmodel import Session, select

from ..models.recurring import RecurringTransaction
from ..models.transaction import Transaction


class RecurringRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self) -> list[RecurringTransaction]:
        statement = (
            select(RecurringTransaction)
            .where(RecurringTransaction.user == self.uid)
            .order_by(RecurringTransaction.next_date, RecurringTransaction.created)
        )
        return self.db.exec(statement).all()

    def read(self, rid: UUID) -> RecurringTransaction | None:
        return self.db.exec(
            select(RecurringTransaction).where(RecurringTransaction.rid == rid, RecurringTransaction.user == self.uid)
        ).first()

    def due(self, today: date) -> list[RecurringTransaction]:
        statement = select(RecurringTransaction).where(
            RecurringTransaction.user == self.uid,
            RecurringTransaction.active == True,  # noqa: E712
            RecurringTransaction.next_date <= today,
        )
        return self.db.exec(statement).all()

    def add(self, rule: RecurringTransaction) -> RecurringTransaction:
        self.db.add(rule)
        self.db.flush()
        return rule

    def delete(self, rule: RecurringTransaction) -> None:
        # What it recorded stays: those transactions just stop pointing at the rule.
        for transaction in self.db.exec(select(Transaction).where(Transaction.recurring_id == rule.rid)).all():
            transaction.recurring_id = None
            self.db.add(transaction)
        self.db.flush()
        self.db.delete(rule)
        self.db.flush()

    def recorded(self, rid: UUID, day: date) -> bool:
        return (
            self.db.exec(
                select(Transaction.tid).where(Transaction.recurring_id == rid, Transaction.recurring_date == day)
            ).first()
            is not None
        )

    @staticmethod
    def users_with_due(db: Session, today: date) -> list[UUID]:
        statement = (
            select(RecurringTransaction.user)
            .where(RecurringTransaction.active == True, RecurringTransaction.next_date <= today)  # noqa: E712
            .distinct()
        )
        return list(db.exec(statement).all())

    @staticmethod
    def uses_account(db: Session, aid: UUID) -> bool:
        """Whether any rule records into or out of the account (so it cannot be deleted)."""
        return (
            db.exec(
                select(RecurringTransaction.rid).where(
                    or_(RecurringTransaction.from_account == aid, RecurringTransaction.to_account == aid)
                )
            ).first()
            is not None
        )
