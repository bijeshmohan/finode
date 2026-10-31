"""Persistence for recurring rules and their split postings, always filtered by the user's id."""

import builtins
from datetime import date
from uuid import UUID

from sqlalchemy import or_, update
from sqlmodel import Session, col, select

from ..models.recurring import RecurringPosting, RecurringTransaction
from ..models.transaction import Transaction


class RecurringRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self) -> builtins.list[RecurringTransaction]:
        statement = (
            select(RecurringTransaction)
            .where(RecurringTransaction.user_id == self.uid)
            .order_by(RecurringTransaction.next_date, RecurringTransaction.created)
        )
        return self.db.exec(statement).all()

    def read(self, recurring_id: UUID) -> RecurringTransaction | None:
        return self.db.exec(
            select(RecurringTransaction).where(
                RecurringTransaction.id == recurring_id, RecurringTransaction.user_id == self.uid
            )
        ).first()

    def due(self, today: date) -> builtins.list[RecurringTransaction]:
        statement = select(RecurringTransaction).where(
            RecurringTransaction.user_id == self.uid,
            RecurringTransaction.active == True,  # noqa: E712
            RecurringTransaction.next_date <= today,
        )
        return self.db.exec(statement).all()

    def add(self, rule: RecurringTransaction) -> RecurringTransaction:
        self.db.add(rule)
        self.db.flush()
        return rule

    def postings(self) -> dict[UUID, builtins.list[RecurringPosting]]:
        """The rows of every split rule, by rule, in the order they were entered."""
        found: dict[UUID, builtins.list[RecurringPosting]] = {}
        statement = (
            select(RecurringPosting).where(RecurringPosting.user_id == self.uid).order_by(RecurringPosting.position)
        )
        for row in self.db.exec(statement).all():
            found.setdefault(row.recurring_id, []).append(row)
        return found

    def set_postings(self, recurring_id: UUID, rows: builtins.list[dict]) -> None:
        for old in self.db.exec(select(RecurringPosting).where(RecurringPosting.recurring_id == recurring_id)).all():
            self.db.delete(old)
        self.db.flush()
        for position, row in enumerate(rows):
            self.db.add(RecurringPosting(user_id=self.uid, recurring_id=recurring_id, position=position, **row))
        self.db.flush()

    def delete(self, rule: RecurringTransaction) -> None:
        self.set_postings(rule.id, [])
        # What it recorded stays: those transactions just stop pointing at the rule.
        for transaction in self.db.exec(select(Transaction).where(Transaction.recurring_id == rule.id)).all():
            transaction.recurring_id = None
            self.db.add(transaction)
        self.db.flush()
        self.db.delete(rule)
        self.db.flush()

    def recorded(self, recurring_id: UUID, day: date) -> bool:
        return (
            self.db.exec(
                select(Transaction.id).where(
                    Transaction.recurring_id == recurring_id, Transaction.recurring_date == day
                )
            ).first()
            is not None
        )

    @staticmethod
    def users_with_due(db: Session, today: date) -> builtins.list[UUID]:
        statement = (
            select(RecurringTransaction.user_id)
            .where(RecurringTransaction.active == True, RecurringTransaction.next_date <= today)  # noqa: E712
            .distinct()
        )
        return list(db.exec(statement).all())

    @staticmethod
    def active_rules_using(db: Session, uid: UUID, aids: set[UUID]) -> builtins.list[RecurringTransaction]:
        """Rules that still run and record into or out of any of these accounts."""
        posting_rules = set(
            db.exec(
                select(RecurringPosting.recurring_id).where(
                    RecurringPosting.user_id == uid, col(RecurringPosting.account_id).in_(aids)
                )
            ).all()
        )
        return [
            rule
            for rule in db.exec(
                select(RecurringTransaction).where(
                    RecurringTransaction.user_id == uid, col(RecurringTransaction.active).is_(True)
                )
            ).all()
            if rule.from_account_id in aids or rule.to_account_id in aids or rule.id in posting_rules
        ]

    @staticmethod
    def merge_conflicts(db: Session, uid: UUID, a: UUID, b: UUID) -> builtins.list[str]:
        """Rules that would end up with an account on both sides if `a` and `b` became one (named by payee)."""
        names = []
        for rule in db.exec(select(RecurringTransaction).where(RecurringTransaction.user_id == uid)).all():
            label = rule.payee or "a recurring transaction"
            if {rule.from_account_id, rule.to_account_id} == {a, b}:
                names.append(label)
                continue
            rows = db.exec(
                select(RecurringPosting).where(
                    RecurringPosting.user_id == uid, RecurringPosting.recurring_id == rule.id
                )
            ).all()
            sides_a = {p.side for p in rows if p.account_id == a}
            sides_b = {p.side for p in rows if p.account_id == b}
            if sides_a and sides_b and sides_a != sides_b:
                names.append(label)
        return names

    @staticmethod
    def rules_using(db: Session, uid: UUID, account_id: UUID) -> int:
        """How many rules (running or paused) use the account."""
        simple = set(
            db.exec(
                select(RecurringTransaction.id).where(
                    RecurringTransaction.user_id == uid,
                    or_(
                        RecurringTransaction.from_account_id == account_id,
                        RecurringTransaction.to_account_id == account_id,
                    ),
                )
            ).all()
        )
        split = set(
            db.exec(
                select(RecurringPosting.recurring_id).where(
                    RecurringPosting.user_id == uid, RecurringPosting.account_id == account_id
                )
            ).all()
        )
        return len(simple | split)

    @staticmethod
    def repoint_account(db: Session, uid: UUID, source: UUID, target: UUID) -> int:
        """Rules that use `source` use `target` instead (a merge). Returns how many rules changed. Nothing is committed."""
        rules = set(
            db.exec(
                select(RecurringTransaction.id).where(
                    RecurringTransaction.user_id == uid,
                    or_(RecurringTransaction.from_account_id == source, RecurringTransaction.to_account_id == source),
                )
            ).all()
        ) | set(
            db.exec(
                select(RecurringPosting.recurring_id).where(
                    RecurringPosting.user_id == uid, RecurringPosting.account_id == source
                )
            ).all()
        )
        db.exec(
            update(RecurringTransaction)
            .where(RecurringTransaction.user_id == uid, RecurringTransaction.from_account_id == source)
            .values(from_account_id=target)
        )
        db.exec(
            update(RecurringTransaction)
            .where(RecurringTransaction.user_id == uid, RecurringTransaction.to_account_id == source)
            .values(to_account_id=target)
        )
        db.exec(
            update(RecurringPosting)
            .where(RecurringPosting.user_id == uid, RecurringPosting.account_id == source)
            .values(account_id=target)
        )
        db.expire_all()
        db.flush()
        return len(rules)

    @staticmethod
    def uses_account(db: Session, account_id: UUID) -> bool:
        """Whether any rule records into or out of the account (so it cannot be deleted)."""
        return (
            db.exec(
                select(RecurringTransaction.id).where(
                    or_(
                        RecurringTransaction.from_account_id == account_id,
                        RecurringTransaction.to_account_id == account_id,
                    )
                )
            ).first()
            is not None
            or db.exec(select(RecurringPosting.id).where(RecurringPosting.account_id == account_id)).first() is not None
        )

    @staticmethod
    def active_rules_for_category(db: Session, uid: UUID, category_id: UUID) -> builtins.list[RecurringTransaction]:
        """Rules that still run and record into this category (on the rule or on one of its rows)."""
        by_rows = set(
            db.exec(
                select(RecurringPosting.recurring_id).where(
                    RecurringPosting.user_id == uid, RecurringPosting.category_id == category_id
                )
            ).all()
        )
        return [
            rule
            for rule in db.exec(
                select(RecurringTransaction).where(
                    RecurringTransaction.user_id == uid, col(RecurringTransaction.active).is_(True)
                )
            ).all()
            if rule.category_id == category_id or rule.id in by_rows
        ]

    @staticmethod
    def uses_category(db: Session, uid: UUID, category_id: UUID) -> bool:
        """Whether any rule (running or not) is labelled with the category."""
        return (
            db.exec(
                select(RecurringTransaction.id).where(
                    RecurringTransaction.user_id == uid, RecurringTransaction.category_id == category_id
                )
            ).first()
            is not None
            or db.exec(
                select(RecurringPosting.id).where(
                    RecurringPosting.user_id == uid, RecurringPosting.category_id == category_id
                )
            ).first()
            is not None
        )

    @staticmethod
    def rules_for_category(db: Session, uid: UUID, category_id: UUID) -> int:
        """How many rules (running or not) are labelled with the category."""
        by_rows = set(
            db.exec(
                select(RecurringPosting.recurring_id).where(
                    RecurringPosting.user_id == uid, RecurringPosting.category_id == category_id
                )
            ).all()
        )
        by_rule = set(
            db.exec(
                select(RecurringTransaction.id).where(
                    RecurringTransaction.user_id == uid, RecurringTransaction.category_id == category_id
                )
            ).all()
        )
        return len(by_rows | by_rule)

    @staticmethod
    def repoint_category(db: Session, uid: UUID, source: UUID, target: UUID) -> int:
        """Rules labelled with `source` are labelled with `target` instead (a merge). Returns how many rules changed."""
        rules = set(
            db.exec(
                select(RecurringTransaction.id).where(
                    RecurringTransaction.user_id == uid, RecurringTransaction.category_id == source
                )
            ).all()
        ) | set(
            db.exec(
                select(RecurringPosting.recurring_id).where(
                    RecurringPosting.user_id == uid, RecurringPosting.category_id == source
                )
            ).all()
        )
        db.exec(
            update(RecurringTransaction)
            .where(RecurringTransaction.user_id == uid, RecurringTransaction.category_id == source)
            .values(category_id=target)
        )
        db.exec(
            update(RecurringPosting)
            .where(RecurringPosting.user_id == uid, RecurringPosting.category_id == source)
            .values(category_id=target)
        )
        db.expire_all()
        db.flush()
        return len(rules)
