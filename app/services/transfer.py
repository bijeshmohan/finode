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
from ..schemas.contact import (
    OpeningBalanceCreate,
    OpeningBalanceUpdate,
    SettlementCreate,
    TransferCreate,
    TransferRead,
)
from ..schemas.transaction import PostingCreate, TransactionCreate, TransactionRead, TransactionUpdate
from .contact import PAYABLE, RECEIVABLE, ContactService
from .contact_errors import (
    ConflictError,
    DuplicateRequestError,
    InsufficientOutstandingBalanceError,
    InvalidTransferPurposeError,
    ReversalBlockedError,
)
from .settlement import SettlementService
from .transaction import TransactionService

TRANSFER_PURPOSES = ("loan", "borrowing", "advance", "gift", "opening")
ALLOWED = {
    "sent": ("loan", "advance", "gift"),
    "received": ("borrowing", "advance", "gift"),
}


class TransferService:
    def __init__(
        self,
        contacts: ContactService,
        transactions: TransactionService,
        ob: ObligationRepository,
        settlements: SettlementService,
    ):
        self.contacts = contacts
        self.accounts = contacts.accounts
        self.transactions = transactions  # made with contacts=True: it may post to a contact's accounts
        self.ob = ob
        self.db = ob.db
        self.settlements = settlements
        self.netting = settlements.netting

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
            roots = self.accounts.ar.root_ids()
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
            self.netting.even_out([contact.id])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(entry, self.ob.party_rows(transaction_id=entry.id)[0], obligation_id)

    def move(self, contact_id: UUID, data: TransferCreate) -> UUID:
        """Money that went to or came from a person, as the "+" screen records it. Money coming from someone who owes you
        pays that back first (and going to someone you owe pays what you owe first); only the rest, or all of it when
        nothing is owed that way, is a new borrowing (from them) or loan (to them). Returns the entry's id."""
        if data.purpose not in ("loan", "borrowing"):
            raise InvalidTransferPurposeError("money moved with a person is a loan or a borrowing here!")
        owes = RECEIVABLE if data.direction == "received" else PAYABLE
        owed = sum((left for _, left in self.settlements.obligations.open_rows(contact_id, owes)), Decimal(0))
        if owed <= 0:
            return self.record(contact_id, data).id
        return self.settlements.record(
            contact_id,
            SettlementCreate(
                direction=data.direction,
                amount=data.amount,
                date=data.date,
                account_id=data.account_id,
                description=data.description,
                excess_as=data.purpose if data.amount > owed else None,
            ),
        ).id

    def name_gift(self, transaction_id: UUID, contact_id: UUID | None, direction: str) -> None:
        """The person an ordinary expense (`sent`) or income (`received`) was a gift to or from: it shows in their activity and
        nothing is owed. The caller saves it with the entry; None takes the name off."""
        for row in self.ob.party_rows(transaction_id=transaction_id):
            if row.purpose == "gift":
                self.db.delete(row)
        self.db.flush()
        if contact_id is not None:
            self.ob.add_party(self.contacts.active(contact_id).id, transaction_id, "gift", direction)

    def gift_of(self, transaction_id: UUID) -> UUID | None:
        """The person an entry was a gift to or from, if it names one."""
        found = [r for r in self.ob.party_rows(transaction_id=transaction_id) if r.purpose == "gift"]
        return found[0].contact_id if found else None

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
            self.netting.even_out([contact.id])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(entry, self.ob.party_rows(transaction_id=entry.id)[0], made.id)

    def _loan_rows(self, transaction_id: UUID, lock: bool = False):
        """The activity row and obligation of an entry that is already a loan or a borrowing (none for an ordinary entry).
        Anything else a contact made (a gift, a shared bill, a settlement, an opening balance) is changed on its own
        terms, not here; and nothing can change once something was settled against it."""
        party = self.ob.party_rows(transaction_id=transaction_id)
        if not party:
            return None, None
        if party[0].purpose not in ("loan", "borrowing"):
            raise InvalidTransferPurposeError(
                "only a loan or a borrowing can be changed here: change the rest on the person's page!"
            )
        owed = self.ob.obligations(source_transaction_id=transaction_id, lock=lock)
        self.netting.release([o.id for o in owed])
        if self.ob.any_settled(owed):
            raise ConflictError("something was paid back against this: reverse that first!")
        return party[0], owed[0] if owed else None

    def convert(
        self,
        transaction_id: UUID,
        contact_id: UUID,
        data: TransferCreate,
        tags: list[str],
        related_id: UUID | None,
    ) -> TransferRead:
        """Make an existing entry a loan or a borrowing with a person, in place: the entry keeps its id, tags and related
        link; its lines move to the person's account, and it gets the activity row and the obligation. An entry that
        already is a loan or borrowing may change person, side, amount, account, day or note, until anything is paid back."""
        if data.purpose not in ("loan", "borrowing"):
            raise InvalidTransferPurposeError("only a loan or a borrowing can be made from an entry!")
        contact = self.contacts.active(contact_id)
        account_id = self.contacts.own_account(data.account_id)
        try:
            party, obligation = self._loan_rows(transaction_id, lock=True)
            self.transactions.update(
                transaction_id,
                TransactionUpdate(
                    date=data.date,
                    payee=contact.name,
                    comment=data.description,
                    postings=self._postings(contact.id, data, account_id),
                    tags=tags,
                    related_id=related_id,
                ),
                commit=False,
            )
            owed = RECEIVABLE if data.direction == "sent" else PAYABLE
            if party is None:
                self.ob.add_party(contact.id, transaction_id, data.purpose, data.direction)
                self.ob.add_obligation(contact.id, transaction_id, data.purpose, owed, data.amount)
            else:
                party.contact_id, party.purpose, party.direction = contact.id, data.purpose, data.direction
                self.db.add(party)
                if obligation is not None:
                    obligation.contact_id, obligation.source_type = contact.id, data.purpose
                    obligation.direction, obligation.original_amount = owed, data.amount
                    self.db.add(obligation)
            self.netting.even_out([contact.id])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.read(transaction_id)

    def detach(self, transaction_id: UUID) -> bool:
        """Before a loan or borrowing is edited into an ordinary entry: its activity row and obligation go (the caller then
        saves the ordinary lines, and rolls everything back if that fails). False for an entry that is not one."""
        party, _ = self._loan_rows(transaction_id, lock=True)
        if party is None:
            return False
        self.ob.purge(transaction_id)
        self.netting.even_out([party.contact_id])
        return True

    def update_opening(self, transaction_id: UUID, data: OpeningBalanceUpdate) -> TransferRead:
        """Change an opening balance (the amount, the day, the note, who owes whom). The same entry is rewritten, so none
        of your accounts or budgets move. Once part of it was paid back the amount cannot go below that and the
        direction cannot change; the owed figures are read again under a row lock."""
        party = self._party(transaction_id)
        if party.purpose != "opening":
            raise InvalidTransferPurposeError("only an opening balance can be changed: reverse it and record it again!")
        contact = self.contacts.active(party.contact_id)
        obligation = self.ob.obligations(source_transaction_id=transaction_id, lock=True)[0]
        sent = data.model_fields_set
        try:
            self.netting.release([obligation.id])
            paid = self.ob.settled([obligation.id]).get(obligation.id, Decimal(0))
            direction = data.direction if "direction" in sent and data.direction else obligation.direction
            amount = data.amount if "amount" in sent and data.amount else obligation.original_amount
            if paid > 0 and direction != obligation.direction:
                raise ConflictError("part of this has been paid back: who owes whom can't change!")
            if amount < paid:
                raise InsufficientOutstandingBalanceError(
                    f"{paid:f} of this has been paid back: the amount can't go below that!"
                )
            ids = self.contacts.account_ids(contact.id)
            opening = self.accounts.opening_balances_account().id
            receivable = direction == "receivable"
            debit, credit = (ids[RECEIVABLE], opening) if receivable else (opening, ids[PAYABLE])
            changes: dict = {
                "postings": [
                    PostingCreate(account_id=debit, side=PostingSide.DEBIT, amount=amount),
                    PostingCreate(account_id=credit, side=PostingSide.CREDIT, amount=amount),
                ]
            }
            if "date" in sent and data.date:
                changes["date"] = data.date
            if "description" in sent:
                changes["comment"] = data.description
            entry = self.transactions.update(transaction_id, TransactionUpdate(**changes), commit=False)
            if entry is None:
                raise InvalidTransferPurposeError("transfer not found!")
            obligation.original_amount, obligation.direction = amount, direction
            party.direction = "sent" if receivable else "received"
            self.db.add_all([obligation, party])
            self.netting.even_out([contact.id])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.read(transaction_id)

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
        entries = self.transactions.read_many([r.transaction_id for r in rows])
        made = {o.source_transaction_id: o.id for o in self.ob.obligations(contact_id=contact_id)}
        reads = [self._read(entries[r.transaction_id], r, made.get(r.transaction_id)) for r in rows]
        return sorted(reads, key=lambda t: (t.date, str(t.id)), reverse=True)

    # ---- reversing ---------------------------------------------------------------------------------

    def reverse(self, transaction_id: UUID) -> None:
        """Undo a transfer for good: the entry, the obligation and the activity row go. Refused once anything has been
        settled against what it left owed (reverse that settlement first)."""
        party = self._party(transaction_id)
        obligations = self.ob.obligations(source_transaction_id=transaction_id, lock=True)
        try:
            self.netting.release([o.id for o in obligations])
            if self.ob.any_settled(obligations):
                raise ReversalBlockedError("something was settled against this: reverse the settlement first!")
            self.ob.purge(transaction_id)
            self.transactions.delete(transaction_id, commit=False)
            self.netting.even_out([party.contact_id])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
