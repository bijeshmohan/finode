"""Money moving between the owner and a contact: loans, borrowings, advances and gifts.

Every transfer is one ordinary ledger entry made through the transaction service, together with what the contact
services keep about it (the activity row, the obligation it leaves, the idempotency key), saved in one commit.

- sent loan or advance: debit "Due from X", credit your account; X owes you (a receivable).
- received borrowing or advance: debit your account, credit "Due to X"; you owe X (a payable).
- gift: spending (sent) or income (received) under a category; nothing is owed.
Nothing here is an expense or income at its principal value, so the budget only moves by the money in the accounts."""

from decimal import Decimal
from uuid import UUID

from ..models.contact import PartyTransaction
from ..models.transaction import PostingSide
from ..repositories.obligation import ObligationRepository
from ..schemas.contact import OpeningBalanceCreate, TransferCreate, TransferRead
from ..schemas.transaction import PostingCreate, TransactionCreate, TransactionRead
from .contact import PAYABLE, RECEIVABLE, ContactService
from .contact_errors import (
    DuplicateRequestError,
    InvalidTransferPurposeError,
    ReversalBlockedError,
)
from .transaction import TransactionService

TRANSFER_PURPOSES = ("loan", "borrowing", "advance", "gift", "opening")
ALLOWED = {
    "sent": ("loan", "advance", "gift"),
    "received": ("borrowing", "advance", "gift"),
}


class TransferService:
    def __init__(self, contacts: ContactService, transactions: TransactionService, ob: ObligationRepository):
        self.contacts = contacts
        self.accounts = contacts.accounts
        self.transactions = transactions  # made with contacts=True: it may post to a contact's accounts
        self.ob = ob
        self.db = ob.db

    # ---- shared with the other contact services ----------------------------------------------------

    def remember(self, key: str | None, transaction_id: UUID) -> None:
        if key:
            self.ob.add_request(key, transaction_id)

    # ---- recording ---------------------------------------------------------------------------------

    def _postings(self, contact_id: UUID, data: TransferCreate, account_id: UUID) -> list[PostingCreate]:
        ids = self.contacts.account_ids(contact_id)
        amount = data.amount
        sent = data.direction == "sent"
        mine = PostingCreate(
            account_id=account_id, side=PostingSide.CREDIT if sent else PostingSide.DEBIT, amount=amount
        )
        if data.purpose == "gift":
            roots = {a.name: a.id for a in self.accounts.ar.list() if a.parent_id is None}
            other = PostingCreate(
                account_id=roots["Expenses" if sent else "Income"],
                side=PostingSide.DEBIT if sent else PostingSide.CREDIT,
                amount=amount,
                category_id=data.category_id,
            )
        elif sent:
            other = PostingCreate(account_id=ids[RECEIVABLE], side=PostingSide.DEBIT, amount=amount)
        else:
            other = PostingCreate(account_id=ids[PAYABLE], side=PostingSide.CREDIT, amount=amount)
        return [other, mine] if sent else [mine, other]

    def record(self, contact_id: UUID, data: TransferCreate, key: str | None = None) -> TransferRead:
        if key and (found := self.ob.request(key)) is not None:
            return self._replay(found.transaction_id, contact_id, data)
        contact = self.contacts.active(contact_id)
        if data.purpose not in ALLOWED[data.direction]:
            raise InvalidTransferPurposeError(
                f"money {data.direction} can be {', '.join(ALLOWED[data.direction])}, not a {data.purpose}!"
            )
        if data.category_id is not None and data.purpose != "gift":
            raise InvalidTransferPurposeError("only a gift has a category: a loan is not spending or income!")
        account_id = self.contacts.own_account(data.account_id)
        try:
            entry = self.transactions.create(
                TransactionCreate(
                    date=data.date,
                    payee=contact.name,
                    comment=data.description,
                    postings=self._postings(contact.id, data, account_id),
                ),
                commit=False,
            )
            self.ob.add_party(contact.id, entry.id, data.purpose, data.direction)
            obligation_id = None
            if data.purpose != "gift":
                owed = RECEIVABLE if data.direction == "sent" else PAYABLE
                obligation_id = self.ob.add_obligation(contact.id, entry.id, data.purpose, owed, data.amount).id
            self.remember(key, entry.id)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(entry, self.ob.party_rows(transaction_id=entry.id)[0], obligation_id)

    def opening_balance(self, contact_id: UUID, data: OpeningBalanceCreate, key: str | None = None) -> TransferRead:
        """What the person already owed before finode: against the system's Opening Balances account, so none of your own
        accounts or budgets move. They owe you (debit "Due from X") or you owe them (credit "Due to X")."""
        if key and (found := self.ob.request(key)) is not None:
            same = self.read(found.transaction_id)
            if (same.contact_id, same.purpose, same.amount, same.date) != (
                contact_id,
                "opening",
                data.amount,
                data.date,
            ):
                raise DuplicateRequestError("this idempotency key was already used for a different request!")
            return same
        contact = self.contacts.active(contact_id)
        ids = self.contacts.account_ids(contact.id)
        opening = self.accounts.opening_balances_account().id
        receivable = data.direction == "receivable"
        mine, theirs = (ids[RECEIVABLE], opening) if receivable else (opening, ids[PAYABLE])
        try:
            entry = self.transactions.create(
                TransactionCreate(
                    date=data.date,
                    payee="Opening balance",
                    comment=data.description,
                    postings=[
                        PostingCreate(account_id=mine, side=PostingSide.DEBIT, amount=data.amount),
                        PostingCreate(account_id=theirs, side=PostingSide.CREDIT, amount=data.amount),
                    ],
                ),
                commit=False,
            )
            self.ob.add_party(contact.id, entry.id, "opening", "sent" if receivable else "received")
            made = self.ob.add_obligation(contact.id, entry.id, "opening", data.direction, data.amount)
            self.remember(key, entry.id)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(entry, self.ob.party_rows(transaction_id=entry.id)[0], made.id)

    def _replay(self, transaction_id: UUID, contact_id: UUID, data: TransferCreate) -> TransferRead:
        """The same idempotency key again: the same transfer is returned, a different request with it is refused."""
        found = self.read(transaction_id)
        if (found.contact_id, found.direction, found.purpose, found.amount, found.date) != (
            contact_id,
            data.direction,
            data.purpose,
            data.amount,
            data.date,
        ):
            raise DuplicateRequestError("this idempotency key was already used for a different request!")
        return found

    # ---- reading -----------------------------------------------------------------------------------

    def _read(self, entry: TransactionRead, party: PartyTransaction, obligation_id: UUID | None) -> TransferRead:
        side = PostingSide.CREDIT if party.direction == "sent" else PostingSide.DEBIT
        mine = next((p for p in entry.postings if p.side == side), None) if party.purpose != "opening" else None
        return TransferRead(
            id=entry.id,
            contact_id=party.contact_id,
            direction=party.direction,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
            purpose=party.purpose,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
            amount=sum((p.amount for p in entry.postings if p.side == PostingSide.DEBIT), Decimal(0)),
            date=entry.date,
            account_id=mine.account_id if mine else None,
            description=entry.comment,
            obligation_id=obligation_id,
        )

    def _party(self, transaction_id: UUID) -> PartyTransaction:
        rows = [r for r in self.ob.party_rows(transaction_id=transaction_id) if r.purpose in TRANSFER_PURPOSES]
        if not rows:
            raise InvalidTransferPurposeError("transfer not found!")
        return rows[0]

    def read(self, transaction_id: UUID) -> TransferRead:
        party = self._party(transaction_id)
        entry = self.transactions.read(transaction_id)
        if entry is None:
            raise InvalidTransferPurposeError("transfer not found!")
        made = self.ob.obligations(source_transaction_id=transaction_id)
        return self._read(entry, party, made[0].id if made else None)

    def list(self, contact_id: UUID) -> list[TransferRead]:
        """A contact's transfers, newest first."""
        self.contacts.get(contact_id)
        rows = [r for r in self.ob.party_rows(contact_id=contact_id) if r.purpose in TRANSFER_PURPOSES]
        entries = {e.id: e for e in (self.transactions.read(r.transaction_id) for r in rows) if e is not None}
        made = {o.source_transaction_id: o.id for o in self.ob.obligations(contact_id=contact_id)}
        reads = [self._read(entries[r.transaction_id], r, made.get(r.transaction_id)) for r in rows]
        return sorted(reads, key=lambda t: (t.date, str(t.id)), reverse=True)

    # ---- reversing ---------------------------------------------------------------------------------

    def reverse(self, transaction_id: UUID) -> None:
        """Undo a transfer for good: the entry, the obligation and the activity row go. Refused once anything has been
        settled against what it left owed (reverse that settlement first)."""
        self._party(transaction_id)
        obligations = self.ob.obligations(source_transaction_id=transaction_id, lock=True)
        if any(self.ob.settled([o.id]).get(o.id) for o in obligations):
            raise ReversalBlockedError("something was settled against this: reverse the settlement first!")
        try:
            self.ob.purge(transaction_id)
            self.transactions.delete(transaction_id, commit=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
