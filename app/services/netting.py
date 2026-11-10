"""Netting off: clearing what a contact owes you against what you owe them.

When a person owes you and you owe them, the two never cancel in the books by themselves (a receivable and a payable are
separate obligations). Netting off clears the smaller side in full and the same amount of the larger, oldest first on
each side, with one ledger entry between their two accounts ("Due to X" debited, "Due from X" credited). None of your
own accounts or budgets move. Each obligation it touches gets a settlement row for the entry, so it is reversed, like
any settlement, by deleting the entry."""

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from ..clock import local_today
from ..models.contact import PartyObligation
from ..models.transaction import PostingSide
from ..repositories.obligation import ObligationRepository
from ..schemas.contact import AllocationRead, NetOffRead
from ..schemas.transaction import PostingCreate, TransactionCreate
from .contact import PAYABLE, RECEIVABLE, ContactService
from .contact_errors import DuplicateRequestError, InvalidSettlementAllocationError, ObligationNotFoundError
from .obligation import ObligationService
from .transaction import TransactionService

ZERO = Decimal(0)


def _take(
    rows: list[tuple[PartyObligation, Decimal]], amount: Decimal
) -> list[tuple[PartyObligation, Decimal, Decimal]]:
    """Oldest first: (obligation, what was owed, what is cleared) until `amount` is used up."""
    out = []
    left = amount
    for row, owed in rows:
        if left <= 0:
            break
        take = min(owed, left)
        out.append((row, owed, take))
        left -= take
    return out


class NettingService:
    def __init__(
        self,
        contacts: ContactService,
        transactions: TransactionService,
        ob: ObligationRepository,
        obligations: ObligationService,
    ):
        self.contacts = contacts
        self.transactions = transactions  # made with contacts=True
        self.ob = ob
        self.obligations = obligations
        self.db = ob.db

    def _plan(self, contact_id: UUID, lock: bool):
        receivables = self.obligations.open_rows(contact_id, RECEIVABLE, lock=lock)
        payables = self.obligations.open_rows(contact_id, PAYABLE, lock=lock)
        owed_to_me = sum((owed for _, owed in receivables), ZERO)
        owed_by_me = sum((owed for _, owed in payables), ZERO)
        amount = min(owed_to_me, owed_by_me)
        if amount <= 0:
            raise InvalidSettlementAllocationError("nothing to net off: it needs an amount owed each way!")
        return (
            _take(receivables, amount),
            _take(payables, amount),
            amount,
            owed_to_me - amount,
            owed_by_me - amount,
        )

    @staticmethod
    def _reads(taken: Sequence[tuple[PartyObligation, Decimal, Decimal]]) -> list[AllocationRead]:
        return [
            AllocationRead(
                obligation_id=row.id, outstanding_before=owed, amount=cleared, outstanding_after=owed - cleared
            )
            for row, owed, cleared in taken
        ]

    def preview(self, contact_id: UUID) -> NetOffRead:
        """What netting off would clear, saving nothing."""
        self.contacts.active(contact_id)
        receivables, payables, amount, receivable_left, payable_left = self._plan(contact_id, lock=False)
        return NetOffRead(
            contact_id=contact_id,
            date=local_today(),
            amount=amount,
            receivables=self._reads(receivables),
            payables=self._reads(payables),
            receivable_left=receivable_left,
            payable_left=payable_left,
        )

    def net_off(self, contact_id: UUID, key: str | None = None) -> NetOffRead:
        if key and (found := self.ob.request(key)) is not None:
            same = self.read(found.transaction_id)
            if same.contact_id != contact_id:
                raise DuplicateRequestError("this idempotency key was already used for a different request!")
            return same
        contact = self.contacts.active(contact_id)
        ids = self.contacts.account_ids(contact.id)
        try:
            receivables, payables, amount, _, _ = self._plan(contact.id, lock=True)
            entry = self.transactions.create(
                TransactionCreate(
                    date=local_today(),
                    payee=contact.name,
                    comment="Netted off",
                    postings=[
                        PostingCreate(account_id=ids[PAYABLE], side=PostingSide.DEBIT, amount=amount),
                        PostingCreate(account_id=ids[RECEIVABLE], side=PostingSide.CREDIT, amount=amount),
                    ],
                ),
                commit=False,
            )
            self.ob.add_party(contact.id, entry.id, "netoff", "received")
            for row, _, cleared in (*receivables, *payables):
                self.ob.add_settlement(row.id, entry.id, cleared)
            if key:
                self.ob.add_request(key, entry.id)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.read(entry.id)

    def read(self, transaction_id: UUID) -> NetOffRead:
        party = [r for r in self.ob.party_rows(transaction_id=transaction_id) if r.purpose == "netoff"]
        entry = self.transactions.read(transaction_id)
        if not party or entry is None:
            raise ObligationNotFoundError
        rows = self.ob.settlements(transaction_id=transaction_id)
        by_id = {o.id: o for o in self.ob.obligations(ids=[r.obligation_id for r in rows])}
        settled = self.ob.settled(list(by_id))

        def reads(direction: str) -> list[AllocationRead]:
            return [
                AllocationRead(
                    obligation_id=r.obligation_id,
                    outstanding_before=by_id[r.obligation_id].original_amount
                    - settled.get(r.obligation_id, ZERO)
                    + r.amount,
                    amount=r.amount,
                    outstanding_after=by_id[r.obligation_id].original_amount - settled.get(r.obligation_id, ZERO),
                )
                for r in rows
                if by_id[r.obligation_id].direction == direction
            ]

        amount = sum((p.amount for p in entry.postings if p.side == PostingSide.DEBIT), ZERO)
        owed = {d: self.obligations.open_rows(party[0].contact_id, d) for d in (RECEIVABLE, PAYABLE)}
        return NetOffRead(
            id=entry.id,
            contact_id=party[0].contact_id,
            date=entry.date,
            amount=amount,
            receivables=reads("receivable"),
            payables=reads("payable"),
            receivable_left=sum((o for _, o in owed[RECEIVABLE]), ZERO),
            payable_left=sum((o for _, o in owed[PAYABLE]), ZERO),
        )

    def reverse(self, transaction_id: UUID) -> None:
        """Undo a net off for good: both sides are owed again."""
        self.read(transaction_id)
        try:
            self.ob.purge(transaction_id)
            self.transactions.delete(transaction_id, commit=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
