"""A contact's figures and activity. The balances come from the ledger (the "Due from" and "Due to" accounts), never
from adding up the records of what was done; the records say how the balance came about."""

from decimal import Decimal
from uuid import UUID

from ..models.contact import PartyTransaction
from ..models.transaction import PostingSide
from ..repositories.obligation import ObligationRepository
from ..repositories.shared_expense import SharedExpenseRepository
from ..repositories.transaction import TransactionRepository
from ..schemas.contact import ActivityPage, ActivityRead, ContactSummary
from .contact import ContactService
from .contact_errors import ContactNotFoundError
from .obligation import outstanding

ZERO = Decimal(0)
RECENT = 5


class ContactSummaryService:
    def __init__(
        self,
        contacts: ContactService,
        tr: TransactionRepository,
        ob: ObligationRepository,
        expenses: SharedExpenseRepository,
    ):
        self.contacts = contacts
        self.tr = tr
        self.ob = ob
        self.expenses = expenses

    def _activity(self, rows: list[PartyTransaction], contact_id: UUID) -> list[ActivityRead]:
        entries = self.tr.read_many([r.transaction_id for r in rows])
        postings = self.tr.postings_for_transactions([r.transaction_id for r in rows])
        shares: dict[UUID, Decimal] = {}
        for expense in self.expenses.list("confirmed"):
            for share in self.expenses.shares(expense.id):
                if share.contact_id == contact_id and expense.transaction_id is not None:
                    shares[expense.transaction_id] = share.share_amount
        items = []
        for r in rows:
            entry = entries.get(r.transaction_id)
            if entry is None:
                continue
            if r.purpose == "expense":
                amount = shares.get(r.transaction_id, ZERO)
            else:  # what moved on the owner's side
                side = PostingSide.DEBIT if r.direction == "received" else PostingSide.CREDIT
                amount = sum((p.amount for p in postings.get(r.transaction_id, []) if p.side == side), ZERO)
            items.append(
                ActivityRead(
                    transaction_id=r.transaction_id,
                    date=entry.date,
                    purpose=r.purpose,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
                    direction=r.direction,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
                    amount=amount,
                    description=entry.payee if r.purpose == "expense" else entry.comment,
                )
            )
        return sorted(items, key=lambda i: (i.date, str(i.transaction_id)), reverse=True)

    def activity(self, contact_id: UUID, purpose: str | None = None, limit: int = 50, offset: int = 0) -> ActivityPage:
        """Everything done with the contact, newest first."""
        self.contacts.get(contact_id)
        rows = self.ob.party_rows(contact_id=contact_id)
        if purpose:
            rows = [r for r in rows if r.purpose == purpose]
        items = self._activity(rows, contact_id)
        return ActivityPage(total=len(items), items=items[offset : offset + limit])

    def summary(self, contact_id: UUID) -> ContactSummary:
        contact = self.contacts.read(contact_id)
        if contact is None:
            raise ContactNotFoundError
        obligations = self.ob.obligations(contact_id=contact_id)
        settled = self.ob.settled([o.id for o in obligations])
        rows = self.ob.party_rows(contact_id=contact_id)
        activity = self._activity(rows, contact_id)

        def total(*sources: str, direction: str) -> Decimal:
            return sum(
                (o.original_amount for o in obligations if o.source_type in sources and o.direction == direction), ZERO
            )

        return ContactSummary(
            contact_id=contact_id,
            total_receivable=contact.receivable,
            total_payable=contact.payable,
            net_balance=contact.net,
            total_lent=total("loan", "advance", direction="receivable"),
            total_borrowed=total("borrowing", "advance", direction="payable"),
            total_expenses_shared=sum((i.amount for i in activity if i.purpose == "expense"), ZERO),
            total_settlements=sum((i.amount for i in activity if i.purpose == "settlement"), ZERO),
            open_obligations=sum(1 for o in obligations if outstanding(o, settled.get(o.id, ZERO)) > 0),
            recent=activity[:RECENT],
        )
