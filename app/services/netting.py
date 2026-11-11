"""Evening out: a person is never owed both ways.

Whatever saves an obligation calls `even_out` before it commits. If the person now owes you and you owe them, the smaller
side is cleared in full and the same amount of the larger, oldest first on each side, with one ledger entry between
their two accounts ("Due to X" debited, "Due from X" credited). None of your own accounts or budgets move. Each
obligation it touches gets a settlement row for the entry. Before something that entry cleared is undone, `release`
deletes it, and the caller evens out again afterwards, so nothing is ever stuck behind it."""

from collections.abc import Iterable, Sequence
from decimal import Decimal
from uuid import UUID

from ..models.contact import Contact, PartyObligation
from ..models.transaction import PostingSide
from ..repositories.obligation import ObligationRepository
from ..schemas.transaction import PostingCreate, TransactionCreate
from .contact import PAYABLE, RECEIVABLE, ContactService
from .obligation import ObligationService
from .transaction import TransactionService

ZERO = Decimal(0)


def _take(rows: list[tuple[PartyObligation, Decimal]], amount: Decimal) -> list[tuple[PartyObligation, Decimal]]:
    """Oldest first: (obligation, what is cleared) until `amount` is used up."""
    out = []
    left = amount
    for row, owed in rows:
        if left <= 0:
            break
        take = min(owed, left)
        out.append((row, take))
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

    @classmethod
    def within(cls, contacts: ContactService, transactions: TransactionService, ob: ObligationRepository):
        """The service for another contact service to call inside its own save."""
        return cls(contacts, transactions, ob, ObligationService(transactions.tr, ob))

    def _even_out_one(self, contact: Contact) -> None:
        receivables = self.obligations.open_rows(contact.id, RECEIVABLE, lock=True)
        payables = self.obligations.open_rows(contact.id, PAYABLE, lock=True)
        amount = min(sum((owed for _, owed in receivables), ZERO), sum((owed for _, owed in payables), ZERO))
        if amount <= 0:
            return
        ids = self.contacts.account_ids(contact.id)
        cleared = (*_take(receivables, amount), *_take(payables, amount))
        # Dated the day the later of the entries it settles happened, so a backdated entry is not evened out "today".
        dated = self.transactions.tr.read_many(list({row.source_transaction_id for row, _ in cleared}))
        entry = self.transactions.create(
            TransactionCreate(
                date=max(e.date for e in dated.values()),
                payee=contact.name,
                comment="Evened out",
                postings=[
                    PostingCreate(account_id=ids[PAYABLE], side=PostingSide.DEBIT, amount=amount),
                    PostingCreate(account_id=ids[RECEIVABLE], side=PostingSide.CREDIT, amount=amount),
                ],
            ),
            commit=False,
        )
        self.ob.add_party(contact.id, entry.id, "netoff", "received")
        for row, part in cleared:
            self.ob.add_settlement(row.id, entry.id, part)

    def even_out(self, contact_ids: Iterable[UUID]) -> None:
        """Part of the save in progress (the caller commits): whoever is now owed both ways is cleared."""
        for contact_id in dict.fromkeys(contact_ids):
            self._even_out_one(self.contacts.get(contact_id))

    def release(self, obligation_ids: Sequence[UUID]) -> None:
        """Before something is undone: the entries that evened these obligations out are deleted, so what they cleared is
        owed again (the caller evens out again once it is done)."""
        done = {r.settlement_transaction_id for r in self.ob.settlements(obligation_ids=list(obligation_ids))}
        for transaction_id in done:
            if any(p.purpose == "netoff" for p in self.ob.party_rows(transaction_id=transaction_id)):
                self.ob.purge(transaction_id)
                self.transactions.delete(transaction_id, commit=False)
