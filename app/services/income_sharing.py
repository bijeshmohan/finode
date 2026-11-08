"""Income shared with contacts.

Money that came in, part of it not yours: rent collected for a co-owner, a refund for the whole group. One ordinary ledger
entry records it:

- your own part is earned (a credit to Income under the category), so only that counts as income;
- a part that belongs to a contact is held for them: credit "Due to X", you owe them (a payable);
- the money lands in your accounts (debits), or a contact received it for you: debit "Due from X", they owe you (a
  receivable).

The entry balances because the parts and the places the money landed both add up to the total. A contact is on one side
only: what they hold for you and what you hold for them are different things to settle."""

import builtins
from decimal import Decimal
from uuid import UUID

from ..models.transaction import PostingSide
from ..repositories.obligation import ObligationRepository
from ..schemas.shared_income import (
    IncomeDepositIn,
    IncomePartRead,
    IncomePreview,
    SharedIncomeCreate,
    SharedIncomeRead,
)
from ..schemas.transaction import PostingCreate, TransactionCreate, TransactionUpdate
from .contact import PAYABLE, RECEIVABLE, ContactService
from .contact_errors import (
    DuplicateRequestError,
    InvalidSharedIncomeError,
    ReversalBlockedError,
    SharedIncomeNotFoundError,
)
from .transaction import TransactionService, decimal_places

ZERO = Decimal(0)
SOURCE = "shared_income"


class IncomeSharingService:
    def __init__(self, contacts: ContactService, transactions: TransactionService, ob: ObligationRepository):
        self.contacts = contacts
        self.transactions = transactions  # made with contacts=True
        self.ob = ob
        self.db = ob.db

    # ---- working out the entry ---------------------------------------------------------------------

    def _check(self, data: SharedIncomeCreate) -> Decimal:
        """Raise what is wrong with a request; otherwise your own part."""
        places = self.transactions.currency().decimals
        amounts = [data.total_amount, *(p.amount for p in (*data.theirs, *data.received_by, *data.deposits))]
        if any(decimal_places(a) > places for a in amounts):
            raise InvalidSharedIncomeError(f"amounts can have at most {places} decimal places!")
        if data.category_id is not None:
            found = next((c for c in self.transactions.cr.list() if c.id == data.category_id), None)
            if found is None or found.kind != "earning":
                raise InvalidSharedIncomeError("the category must be one of your income categories!")
            if found.closed_on is not None:
                raise InvalidSharedIncomeError(f"category '{found.name}' is closed: reopen it to use it!")
        if not data.theirs and not data.received_by:
            raise InvalidSharedIncomeError("name a person: a part that is theirs, or money they received for you!")
        held = [p.contact_id for p in data.theirs]
        got = [p.contact_id for p in data.received_by]
        if len(set(held)) != len(held) or len(set(got)) != len(got):
            raise InvalidSharedIncomeError("a person is listed twice!")
        if set(held) & set(got):
            raise InvalidSharedIncomeError("a person can't have both a part of this and have received it for you!")
        for contact_id in (*held, *got):
            self.contacts.active(contact_id)
        accounts = [d.account_id for d in data.deposits]
        if len(set(accounts)) != len(accounts):
            raise InvalidSharedIncomeError("an account is listed twice!")
        for account_id in accounts:
            self.contacts.own_account(account_id)
        mine = data.total_amount - sum((p.amount for p in data.theirs), ZERO)
        if mine < 0:
            raise InvalidSharedIncomeError("their parts add up to more than the total!")
        landed = sum((d.amount for d in data.deposits), ZERO) + sum((p.amount for p in data.received_by), ZERO)
        if landed != data.total_amount:
            raise InvalidSharedIncomeError(
                f"the money received adds up to {landed:f}, not the total {data.total_amount:f}: say where the rest went!"
            )
        return mine

    def _lines(self, data: SharedIncomeCreate, mine: Decimal) -> builtins.list[PostingCreate]:
        roots = {a.name: a.id for a in self.contacts.accounts.ar.list() if a.parent_id is None}
        lines: list[PostingCreate] = []
        if mine > 0:
            lines.append(
                PostingCreate(
                    account_id=roots["Income"], side=PostingSide.CREDIT, amount=mine, category_id=data.category_id
                )
            )
        for part in data.theirs:
            ids = self.contacts.account_ids(part.contact_id)
            lines.append(PostingCreate(account_id=ids[PAYABLE], side=PostingSide.CREDIT, amount=part.amount))
        for deposit in data.deposits:
            lines.append(PostingCreate(account_id=deposit.account_id, side=PostingSide.DEBIT, amount=deposit.amount))
        for part in data.received_by:
            ids = self.contacts.account_ids(part.contact_id)
            lines.append(PostingCreate(account_id=ids[RECEIVABLE], side=PostingSide.DEBIT, amount=part.amount))
        return lines

    def _names(self) -> dict[UUID, str]:
        return {c.id: c.name for c in self.contacts.cr.list()}

    def _describe(self, data: SharedIncomeCreate, mine: Decimal) -> IncomePreview:
        names = self._names()
        return IncomePreview(
            description=data.description,
            total_amount=data.total_amount,
            date=data.date,
            category_id=data.category_id,
            your_income=mine,
            theirs=[
                IncomePartRead(contact_id=p.contact_id, name=names[p.contact_id], amount=p.amount) for p in data.theirs
            ],
            received_by=[
                IncomePartRead(contact_id=p.contact_id, name=names[p.contact_id], amount=p.amount)
                for p in data.received_by
            ],
            deposits=data.deposits,
        )

    def preview(self, data: SharedIncomeCreate) -> IncomePreview:
        """What the entry would do, saving nothing."""
        return self._describe(data, self._check(data))

    # ---- reading -----------------------------------------------------------------------------------

    def read(self, transaction_id: UUID) -> SharedIncomeRead:
        party = self.ob.party_rows(transaction_id=transaction_id)
        entry = self.transactions.read(transaction_id)
        if entry is None or not party or {r.purpose for r in party} != {"income"}:
            raise SharedIncomeNotFoundError
        names = self._names()
        owed = self.ob.obligations(source_transaction_id=transaction_id)
        parts = {
            direction: [
                IncomePartRead(contact_id=o.contact_id, name=names.get(o.contact_id, ""), amount=o.original_amount)
                for o in owed
                if o.direction == direction
            ]
            for direction in ("payable", "receivable")
        }
        contact_accounts = self.contacts.accounts.ar.contact_account_ids()
        income = next((p for p in entry.postings if p.side == PostingSide.CREDIT and p.category_id is not None), None)
        total = sum((p.amount for p in entry.postings if p.side == PostingSide.DEBIT), ZERO)
        return SharedIncomeRead(
            transaction_id=transaction_id,
            description=entry.payee or "",
            total_amount=total,
            date=entry.date,
            category_id=income.category_id if income else None,
            your_income=income.amount if income else ZERO,
            theirs=parts["payable"],
            received_by=parts["receivable"],
            deposits=[
                IncomeDepositIn(account_id=p.account_id, amount=p.amount)
                for p in entry.postings
                if p.side == PostingSide.DEBIT and p.account_id not in contact_accounts
            ],
        )

    # ---- writing -----------------------------------------------------------------------------------

    def _save(
        self,
        data: SharedIncomeCreate,
        comment: str | None,
        tags: builtins.list[str],
        related_id: UUID | None,
        onto: UUID | None,
        key: str | None,
    ) -> UUID:
        """Record the entry and everything about it (the caller commits). With `onto`, an entry that already exists
        becomes the shared income, in place (it keeps its id)."""
        mine = self._check(data)
        lines = self._lines(data, mine)
        if onto is None:
            entry = self.transactions.create(
                TransactionCreate(
                    date=data.date,
                    payee=data.description,
                    comment=comment,
                    postings=lines,
                    tags=tags,
                    related_id=related_id,
                ),
                commit=False,
            )
        else:
            changed = self.transactions.update(
                onto,
                TransactionUpdate(
                    date=data.date,
                    payee=data.description,
                    comment=comment,
                    postings=lines,
                    tags=tags,
                    related_id=related_id,
                ),
                commit=False,
            )
            if changed is None:
                raise SharedIncomeNotFoundError
            entry = changed
        for part in data.theirs:
            self.ob.add_party(part.contact_id, entry.id, "income", "received")
            self.ob.add_obligation(part.contact_id, entry.id, SOURCE, "payable", part.amount)
        for part in data.received_by:
            self.ob.add_party(part.contact_id, entry.id, "income", "sent")
            self.ob.add_obligation(part.contact_id, entry.id, SOURCE, "receivable", part.amount)
        if key:
            self.ob.add_request(key, entry.id)
        self.db.flush()
        return entry.id

    def create(
        self,
        data: SharedIncomeCreate,
        key: str | None = None,
        comment: str | None = None,
        tags: builtins.list[str] | None = None,
        related_id: UUID | None = None,
    ) -> SharedIncomeRead:
        if key and (found := self.ob.request(key)) is not None:
            same = self.read(found.transaction_id)
            if (same.description, same.total_amount, same.date) != (data.description, data.total_amount, data.date):
                raise DuplicateRequestError("this idempotency key was already used for a different request!")
            return same
        try:
            made = self._save(data, comment, tags or [], related_id, None, key)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.read(made)

    def detach(self, transaction_id: UUID) -> bool:
        """Before income shared with people is edited into something else: its activity rows and obligations go (the caller
        then saves the new lines and rolls everything back if that fails). False for an entry that is not one; refused
        once anything was settled against what it left owed."""
        party = self.ob.party_rows(transaction_id=transaction_id)
        if not party or {r.purpose for r in party} != {"income"}:
            return False
        owed = self.ob.obligations(source_transaction_id=transaction_id, lock=True)
        if any(self.ob.settled([o.id]).get(o.id) for o in owed):
            raise ReversalBlockedError("something was paid back against this: reverse that first!")
        self.ob.purge(transaction_id)
        return True

    def convert(
        self,
        transaction_id: UUID,
        data: SharedIncomeCreate,
        comment: str | None,
        tags: builtins.list[str],
        related_id: UUID | None,
    ) -> SharedIncomeRead:
        """Make an existing entry income shared with people, in place: it keeps its id, its lines become the shared
        income's and the activity rows and obligations are made. An entry that already is shared income is re-recorded
        with the new parts (until something was paid back)."""
        try:
            self.detach(transaction_id)
            self._save(data, comment, tags, related_id, transaction_id, None)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.read(transaction_id)

    def cancel(self, transaction_id: UUID) -> None:
        """Reverse shared income for good: the entry, what it left owed and its activity rows go. Refused once anything was
        settled against what it left owed."""
        try:
            if not self.detach(transaction_id):
                raise SharedIncomeNotFoundError
            self.transactions.delete(transaction_id, commit=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
