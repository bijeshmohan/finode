"""What contacts owe and are owed. An obligation never changes; what is still owed is its amount less the settlements
made against it, worked out here every time, so there is no balance to keep in step."""

import builtins
from decimal import Decimal
from uuid import UUID

from ..models.contact import PartyObligation
from ..repositories.obligation import ObligationRepository
from ..repositories.transaction import TransactionRepository
from ..schemas.contact import ObligationRead
from .contact_errors import ObligationNotFoundError

ZERO = Decimal(0)


def outstanding(obligation: PartyObligation, settled: Decimal) -> Decimal:
    return obligation.original_amount - settled


class ObligationService:
    def __init__(self, tr: TransactionRepository, ob: ObligationRepository):
        self.tr = tr
        self.ob = ob

    def _reads(self, rows: list[PartyObligation]) -> list[ObligationRead]:
        settled = self.ob.settled([o.id for o in rows])
        entries = self.tr.read_many(list({o.source_transaction_id for o in rows}))
        reads = []
        for o in rows:
            done = settled.get(o.id, ZERO)
            left = outstanding(o, done)
            entry = entries.get(o.source_transaction_id)
            reads.append(
                ObligationRead(
                    id=o.id,
                    contact_id=o.contact_id,
                    source_transaction_id=o.source_transaction_id,
                    source_type=o.source_type,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
                    direction=o.direction,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
                    # a shared expense is named by its payee; a transfer has only the note it was given
                    description=(entry.payee if o.source_type == "shared_expense" else entry.comment)
                    if entry
                    else None,
                    date=entry.date if entry else o.created.date(),
                    original_amount=o.original_amount,
                    settled_amount=done,
                    outstanding_amount=left,
                    status="settled" if left <= 0 else "open" if done == 0 else "partially_settled",
                )
            )
        return reads

    def list(self, contact_id: UUID, direction: str | None = None, open_only: bool = False) -> list[ObligationRead]:
        """A contact's obligations, oldest first (by the day of the entry that made them)."""
        reads = self._reads(self.ob.obligations(contact_id=contact_id, direction=direction))
        if open_only:
            reads = [r for r in reads if r.outstanding_amount > 0]
        return sorted(reads, key=lambda r: (r.date, str(r.id)))

    def read(self, obligation_id: UUID) -> ObligationRead:
        row = self.ob.read(obligation_id)
        if row is None:
            raise ObligationNotFoundError
        return self._reads([row])[0]

    def open_rows(
        self, contact_id: UUID, direction: str, lock: bool = False
    ) -> builtins.list[tuple[PartyObligation, Decimal]]:
        """The contact's obligations in one direction that still have something owed, oldest first, with what is owed.
        With `lock` the rows are locked first and the settled sums read after, so the figures are the ones the caller
        may rely on until it commits."""
        rows = self.ob.obligations(contact_id=contact_id, direction=direction, lock=lock)
        settled = self.ob.settled([o.id for o in rows])
        entries = self.tr.read_many(list({o.source_transaction_id for o in rows}))
        found = [(o, outstanding(o, settled.get(o.id, ZERO))) for o in rows]
        found = [(o, left) for o, left in found if left > 0]
        found.sort(key=lambda pair: (entries[pair[0].source_transaction_id].date, pair[0].created, str(pair[0].id)))
        return found
