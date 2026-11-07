"""Persistence for what contacts owe and what they did: party transactions, obligations, settlements and the
idempotency keys. Always filtered by the user's id."""

import builtins
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlmodel import Session, col, func, select

from ..models.contact import ContactRequest, ObligationSettlement, PartyObligation, PartyTransaction
from ..models.transaction import Transaction

ZERO = Decimal(0)


class ObligationRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    # ---- activity ----------------------------------------------------------------------------------

    def add_party(self, contact_id: UUID, transaction_id: UUID, purpose: str, direction: str) -> PartyTransaction:
        row = PartyTransaction(
            user_id=self.uid, contact_id=contact_id, transaction_id=transaction_id, purpose=purpose, direction=direction
        )
        self.db.add(row)
        self.db.flush()
        return row

    def party_rows(
        self, contact_id: UUID | None = None, transaction_id: UUID | None = None
    ) -> builtins.list[PartyTransaction]:
        statement = select(PartyTransaction).where(PartyTransaction.user_id == self.uid)
        if contact_id is not None:
            statement = statement.where(PartyTransaction.contact_id == contact_id)
        if transaction_id is not None:
            statement = statement.where(PartyTransaction.transaction_id == transaction_id)
        return list(self.db.exec(statement).all())

    def last_activity(self) -> dict[UUID, date]:
        """The day of the latest entry done with each contact."""
        rows = self.db.exec(
            select(PartyTransaction.contact_id, func.max(Transaction.date))
            .join(Transaction, col(Transaction.id) == col(PartyTransaction.transaction_id))
            .where(PartyTransaction.user_id == self.uid)
            .group_by(PartyTransaction.contact_id)
        ).all()
        return dict(rows)

    # ---- obligations -------------------------------------------------------------------------------

    def add_obligation(
        self, contact_id: UUID, transaction_id: UUID, source_type: str, direction: str, amount: Decimal
    ) -> PartyObligation:
        row = PartyObligation(
            user_id=self.uid,
            contact_id=contact_id,
            source_transaction_id=transaction_id,
            source_type=source_type,
            direction=direction,
            original_amount=amount,
        )
        self.db.add(row)
        self.db.flush()
        return row

    def read(self, obligation_id: UUID) -> PartyObligation | None:
        return self.db.exec(
            select(PartyObligation).where(PartyObligation.user_id == self.uid, PartyObligation.id == obligation_id)
        ).first()

    def obligations(
        self,
        contact_id: UUID | None = None,
        direction: str | None = None,
        source_transaction_id: UUID | None = None,
        ids: builtins.list[UUID] | None = None,
        lock: bool = False,
    ) -> builtins.list[PartyObligation]:
        """Obligations, oldest first. `lock` takes a row lock on Postgres so two settlements of the same obligation
        queue up and the second one sees what the first took."""
        statement = select(PartyObligation).where(PartyObligation.user_id == self.uid)
        if contact_id is not None:
            statement = statement.where(PartyObligation.contact_id == contact_id)
        if direction is not None:
            statement = statement.where(PartyObligation.direction == direction)
        if source_transaction_id is not None:
            statement = statement.where(PartyObligation.source_transaction_id == source_transaction_id)
        if ids is not None:
            statement = statement.where(col(PartyObligation.id).in_(ids))
        statement = statement.order_by(col(PartyObligation.created), col(PartyObligation.id))
        if lock:
            statement = statement.with_for_update()
        return list(self.db.exec(statement).all())

    def settled(self, obligation_ids: builtins.list[UUID] | None = None) -> dict[UUID, Decimal]:
        """How much of each obligation has been cleared."""
        statement = select(ObligationSettlement.obligation_id, func.sum(ObligationSettlement.amount)).where(
            ObligationSettlement.user_id == self.uid
        )
        if obligation_ids is not None:
            statement = statement.where(col(ObligationSettlement.obligation_id).in_(obligation_ids))
        rows = self.db.exec(statement.group_by(ObligationSettlement.obligation_id)).all()
        return {obligation_id: Decimal(total) for obligation_id, total in rows}

    def add_settlement(self, obligation_id: UUID, transaction_id: UUID, amount: Decimal) -> ObligationSettlement:
        row = ObligationSettlement(
            user_id=self.uid, obligation_id=obligation_id, settlement_transaction_id=transaction_id, amount=amount
        )
        self.db.add(row)
        self.db.flush()
        return row

    def settlements(
        self, transaction_id: UUID | None = None, obligation_ids: builtins.list[UUID] | None = None
    ) -> builtins.list[ObligationSettlement]:
        statement = select(ObligationSettlement).where(ObligationSettlement.user_id == self.uid)
        if transaction_id is not None:
            statement = statement.where(ObligationSettlement.settlement_transaction_id == transaction_id)
        if obligation_ids is not None:
            statement = statement.where(col(ObligationSettlement.obligation_id).in_(obligation_ids))
        return list(self.db.exec(statement.order_by(col(ObligationSettlement.created))).all())

    # ---- idempotency -------------------------------------------------------------------------------

    def request(self, key: str) -> ContactRequest | None:
        return self.db.exec(
            select(ContactRequest).where(ContactRequest.user_id == self.uid, ContactRequest.key == key)
        ).first()

    def add_request(self, key: str, transaction_id: UUID) -> None:
        self.db.add(ContactRequest(user_id=self.uid, key=key, transaction_id=transaction_id))
        self.db.flush()

    # ---- reversing ---------------------------------------------------------------------------------

    def purge(self, transaction_id: UUID) -> None:
        """Remove everything the contact services recorded about an entry (the entry itself is the caller's to delete)."""
        for row in self.settlements(transaction_id=transaction_id):
            self.db.delete(row)
        for obligation in self.obligations(source_transaction_id=transaction_id):
            self.db.delete(obligation)
        for row in self.party_rows(transaction_id=transaction_id):
            self.db.delete(row)
        for request in self.db.exec(
            select(ContactRequest).where(
                ContactRequest.user_id == self.uid, ContactRequest.transaction_id == transaction_id
            )
        ).all():
            self.db.delete(request)
        self.db.flush()
