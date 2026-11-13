"""Settling up with a contact: they pay back what they owe you, or you pay back what you owe them.

A settlement is one ordinary ledger entry (money in or out of one of your accounts against "Due from X" or "Due to X")
plus the allocations that say which obligations it cleared and by how much. Money is cleared oldest first (`fifo`) or
as the owner says (`manual`), never beyond what is owed: more than is owed is refused unless the owner says what the
rest is (a new loan, borrowing or advance, or a gift), so no obligation ever goes negative.

The owed figures are read again inside the transaction, under a row lock on the obligations, so two settlements of the
same obligation queue up and the second sees what the first took.

Budget: paying back a share of an expense that a contact paid for you is where that spending reaches your budget, if the
original entry touched none of your budget's accounts (a bill a friend paid for you moved no budget money then): the
payment's line carries the expense's category. Paying back a loan's principal is not spending."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import NoReturn
from uuid import UUID

from ..models.contact import ObligationSettlement, PartyObligation, PartyTransaction
from ..models.transaction import PostingSide
from ..repositories.obligation import ObligationRepository
from ..repositories.shared_expense import SharedExpenseRepository
from ..schemas.contact import (
    AllocationRead,
    SettlementCreate,
    SettlementPreview,
    SettlementRead,
)
from ..schemas.transaction import PostingCreate, TransactionCreate, TransactionRead
from .contact import PAYABLE, RECEIVABLE, ContactService
from .contact_errors import (
    DuplicateRequestError,
    InsufficientOutstandingBalanceError,
    InvalidSettlementAllocationError,
    ObligationAlreadySettledError,
    ObligationNotFoundError,
    ReversalBlockedError,
)
from .netting import NettingService
from .obligation import ObligationService, outstanding
from .transaction import TransactionService

ZERO = Decimal(0)
EXCESS_USES = {"received": ("borrowing", "advance", "gift"), "sent": ("loan", "advance", "gift")}


@dataclass
class _Allocation:
    obligation: PartyObligation
    before: Decimal
    amount: Decimal


@dataclass
class _Plan:
    allocations: list[_Allocation] = field(default_factory=list)
    excess: Decimal = ZERO

    @property
    def allocated(self) -> Decimal:
        return sum((a.amount for a in self.allocations), ZERO)


class SettlementService:
    def __init__(
        self,
        contacts: ContactService,
        transactions: TransactionService,
        ob: ObligationRepository,
        obligations: ObligationService,
        expenses: SharedExpenseRepository,
    ):
        self.contacts = contacts
        self.transactions = transactions  # made with contacts=True
        self.ob = ob
        self.obligations = obligations
        self.expenses = expenses
        self.db = ob.db
        self.netting = NettingService(contacts, transactions, ob, obligations)

    # ---- working out what is cleared ---------------------------------------------------------------

    def _plan(self, contact_id: UUID, data: SettlementCreate, lock: bool) -> _Plan:
        direction = RECEIVABLE if data.direction == "received" else PAYABLE
        open_rows = self.obligations.open_rows(contact_id, direction, lock=lock)
        plan = _Plan()
        if data.allocation_method == "fifo":
            if data.allocations:
                raise InvalidSettlementAllocationError(
                    "allocations are for a manual settlement: leave them out for fifo!"
                )
            left = data.amount
            for row, owed in open_rows:
                if left <= 0:
                    break
                take = min(owed, left)
                plan.allocations.append(_Allocation(row, owed, take))
                left -= take
            plan.excess = left
            return plan
        if not data.allocations:
            raise InvalidSettlementAllocationError(
                "a manual settlement needs allocations: which obligations, how much!"
            )
        owed_by_id = {row.id: (row, owed) for row, owed in open_rows}
        seen: set[UUID] = set()
        for item in data.allocations:
            if item.obligation_id in seen:
                raise InvalidSettlementAllocationError("an obligation is listed twice!")
            seen.add(item.obligation_id)
            found = owed_by_id.get(item.obligation_id)
            if found is None:
                self._explain_missing(contact_id, direction, item.obligation_id)
            row, owed = found
            if item.amount > owed:
                raise InsufficientOutstandingBalanceError(f"only {owed:f} is still owed on that, not {item.amount:f}!")
            plan.allocations.append(_Allocation(row, owed, item.amount))
        total = plan.allocated
        if total > data.amount:
            raise InvalidSettlementAllocationError(
                f"the allocations add up to {total:f}, more than the settlement of {data.amount:f}!"
            )
        plan.excess = data.amount - total
        return plan

    def _explain_missing(self, contact_id: UUID, direction: str, obligation_id: UUID) -> NoReturn:
        row = self.ob.read(obligation_id)
        if row is None:
            raise ObligationNotFoundError
        if row.contact_id != contact_id or row.direction != direction:
            raise InvalidSettlementAllocationError(
                "that obligation is not one this settlement can clear: it is another contact's or the other way round!"
            )
        raise ObligationAlreadySettledError("nothing is left to settle on that obligation!")

    def _check_excess(self, data: SettlementCreate, plan: _Plan) -> None:
        if plan.excess > 0 and data.excess_as is None:
            raise InvalidSettlementAllocationError(
                f"{plan.excess:f} more than is owed: say what the rest is (excess_as: "
                f"{', '.join(EXCESS_USES[data.direction])}) or settle less!"
            )
        if plan.excess == 0 and data.excess_as is not None:
            raise InvalidSettlementAllocationError("nothing is left over: leave out excess_as!")
        if data.excess_as is not None and data.excess_as not in EXCESS_USES[data.direction]:
            raise InvalidSettlementAllocationError(
                f"money {data.direction} can be a {', '.join(EXCESS_USES[data.direction])}, not a {data.excess_as}!"
            )
        if data.excess_category_id is not None and data.excess_as != "gift":
            raise InvalidSettlementAllocationError("only a gift has a category!")

    def preview(self, contact_id: UUID, data: SettlementCreate) -> SettlementPreview:
        """What a settlement would clear, saving nothing."""
        self.contacts.active(contact_id)
        plan = self._plan(contact_id, data, lock=False)
        if data.excess_as is not None and plan.excess > 0:
            self._check_excess(data, plan)  # no excess_as yet is fine here: the preview says what the rest is
        direction = RECEIVABLE if data.direction == "received" else PAYABLE
        owing = sum((owed for _, owed in self.obligations.open_rows(contact_id, direction, lock=False)), ZERO)
        return SettlementPreview(
            direction=data.direction,
            amount=data.amount,
            allocations=[self._alloc_read(a) for a in plan.allocations],
            allocated=plan.allocated,
            excess=plan.excess,
            excess_as=data.excess_as if plan.excess > 0 else None,
            remaining=owing - plan.allocated,
        )

    @staticmethod
    def _alloc_read(a: _Allocation) -> AllocationRead:
        return AllocationRead(
            obligation_id=a.obligation.id,
            outstanding_before=a.before,
            amount=a.amount,
            outstanding_after=a.before - a.amount,
        )

    # ---- the ledger lines --------------------------------------------------------------------------

    def _counted_categories(self, plan: _Plan, account_id: UUID) -> dict[UUID | None, Decimal]:
        """For a payment to a contact: the part of what is cleared that is spending reaching the budget now, by
        category (see the module note). Nothing when the payment does not leave the budget."""
        every = {a.id: a for a in self.contacts.accounts.ar.list()}
        if not every[account_id].on_budget:
            return {}
        shares = [a for a in plan.allocations if a.obligation.source_type == "shared_expense"]
        sources = [a.obligation.source_transaction_id for a in shares]
        postings = self.transactions.tr.postings_for_transactions(sources)  # one read each, however many bills
        expenses = self.expenses.by_transactions(sources)
        counted: dict[UUID | None, Decimal] = {}
        for a in shares:
            source = a.obligation.source_transaction_id
            if any(every[p.account_id].on_budget for p in postings.get(source, []) if p.account_id in every):
                continue  # it was counted when it was recorded
            expense = expenses.get(source)
            category = expense.category_id if expense else None
            if category is None:
                category = self.transactions.cr.ensure_uncategorised("spending").id
            counted[category] = counted.get(category, ZERO) + a.amount
        return counted

    def _postings(self, contact_id: UUID, data: SettlementCreate, plan: _Plan, account_id: UUID) -> list[PostingCreate]:
        ids = self.contacts.account_ids(contact_id)
        roots = self.contacts.accounts.ar.root_ids()
        received = data.direction == "received"
        mine = PostingCreate(
            account_id=account_id, side=PostingSide.DEBIT if received else PostingSide.CREDIT, amount=data.amount
        )
        lines = [mine]
        if plan.allocated > 0:
            if received:
                lines.append(PostingCreate(account_id=ids[RECEIVABLE], side=PostingSide.CREDIT, amount=plan.allocated))
            else:
                counted = self._counted_categories(plan, account_id)
                plain = plan.allocated - sum(counted.values(), ZERO)
                if plain > 0:
                    lines.append(PostingCreate(account_id=ids[PAYABLE], side=PostingSide.DEBIT, amount=plain))
                lines += [
                    PostingCreate(account_id=ids[PAYABLE], side=PostingSide.DEBIT, amount=amount, category_id=category)
                    for category, amount in counted.items()
                ]
        if plan.excess > 0:
            if data.excess_as == "gift":
                lines.append(
                    PostingCreate(
                        account_id=roots["Income" if received else "Expenses"],
                        side=PostingSide.CREDIT if received else PostingSide.DEBIT,
                        amount=plan.excess,
                        category_id=data.excess_category_id,
                    )
                )
            elif received:  # they paid more than they owed and it is now money you owe them
                lines.append(PostingCreate(account_id=ids[PAYABLE], side=PostingSide.CREDIT, amount=plan.excess))
            else:  # you paid more than you owed and now they owe you
                lines.append(PostingCreate(account_id=ids[RECEIVABLE], side=PostingSide.DEBIT, amount=plan.excess))
        return lines

    # ---- recording ---------------------------------------------------------------------------------

    def record(self, contact_id: UUID, data: SettlementCreate, key: str | None = None) -> SettlementRead:
        if key and (found := self.ob.request(key)) is not None:
            return self._replay(found.transaction_id, contact_id, data)
        contact = self.contacts.active(contact_id)
        account_id = self.contacts.own_account(data.account_id)
        try:
            plan = self._plan(contact.id, data, lock=True)
            self._check_excess(data, plan)
            entry = self.transactions.create(
                TransactionCreate(
                    date=data.date,
                    payee=contact.name,
                    comment=data.description,
                    postings=self._postings(contact.id, data, plan, account_id),
                ),
                commit=False,
            )
            self.ob.add_party(contact.id, entry.id, "settlement", data.direction)
            for a in plan.allocations:
                self.ob.add_settlement(a.obligation.id, entry.id, a.amount)
            if plan.excess > 0 and data.excess_as in ("loan", "borrowing", "advance"):
                owed = PAYABLE if data.direction == "received" else RECEIVABLE
                self.ob.add_obligation(contact.id, entry.id, data.excess_as, owed, plan.excess)
            if key:
                self.ob.add_request(key, entry.id)
            self.netting.even_out([contact.id])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.read(entry.id)

    def _replay(self, transaction_id: UUID, contact_id: UUID, data: SettlementCreate) -> SettlementRead:
        found = self.read(transaction_id)
        if (found.contact_id, found.direction, found.amount, found.date) != (
            contact_id,
            data.direction,
            data.amount,
            data.date,
        ):
            raise DuplicateRequestError("this idempotency key was already used for a different request!")
        return found

    # ---- reading -----------------------------------------------------------------------------------

    def _party(self, transaction_id: UUID) -> PartyTransaction:
        rows = [r for r in self.ob.party_rows(transaction_id=transaction_id) if r.purpose == "settlement"]
        if not rows:
            raise ObligationNotFoundError
        return rows[0]

    def _reads(self, contact_id: UUID, pairs: list[tuple[TransactionRead, PartyTransaction]]) -> list[SettlementRead]:
        """Settlements with one contact, in the order given. Three queries however many there are: the contact's
        obligations, what was cleared against them, and the days of the other entries that cleared them."""
        owed = {o.id: o for o in self.ob.obligations(contact_id=contact_id)}
        left_over: dict[UUID, PartyObligation] = {}  # what a settlement's excess left owed, by the settling entry
        for o in owed.values():
            left_over.setdefault(o.source_transaction_id, o)
        cleared = self.ob.settlements(obligation_ids=list(owed)) if owed else []
        by_entry: dict[UUID, list[ObligationSettlement]] = {}
        by_obligation: dict[UUID, list[ObligationSettlement]] = {}
        for r in cleared:
            by_entry.setdefault(r.settlement_transaction_id, []).append(r)
            by_obligation.setdefault(r.obligation_id, []).append(r)
        days = {entry.id: entry.date for entry, _ in pairs}
        touched = {r.obligation_id for entry_id in days for r in by_entry.get(entry_id, [])}
        others = {r.settlement_transaction_id for r in cleared if r.obligation_id in touched} - set(days)
        if others:
            days |= {e.id: e.date for e in self.transactions.tr.read_many(list(others)).values()}

        def read(entry: TransactionRead, party: PartyTransaction) -> SettlementRead:
            mine = PostingSide.DEBIT if party.direction == "received" else PostingSide.CREDIT
            total = sum((p.amount for p in entry.postings if p.side == mine), ZERO)
            rows = by_entry.get(entry.id, [])
            allocations = []
            for row in rows:
                on_it = by_obligation[row.obligation_id]
                # What had been cleared by entries before this one: by date, then by when the row was made.
                before = sum(
                    (
                        r.amount
                        for r in on_it
                        if r.id != row.id and (days[r.settlement_transaction_id], r.created) < (entry.date, row.created)
                    ),
                    ZERO,
                )
                allocations.append(
                    AllocationRead(
                        obligation_id=row.obligation_id,
                        outstanding_before=outstanding(owed[row.obligation_id], before),
                        amount=row.amount,
                        outstanding_after=outstanding(owed[row.obligation_id], sum((r.amount for r in on_it), ZERO)),
                    )
                )
            excess = total - sum((r.amount for r in rows), ZERO)
            made = left_over.get(entry.id)
            return SettlementRead(
                id=entry.id,
                contact_id=party.contact_id,
                direction=party.direction,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
                amount=total,
                date=entry.date,
                account_id=next((p.account_id for p in entry.postings if p.side == mine), None),
                description=entry.comment,
                allocations=allocations,
                excess=excess,
                # pyrefly: ignore[bad-argument-type]  # one of the excess uses
                excess_as=made.source_type if made else ("gift" if excess > 0 else None),
                excess_obligation_id=made.id if made else None,
            )

        return [read(entry, party) for entry, party in pairs]

    def read(self, transaction_id: UUID) -> SettlementRead:
        party = self._party(transaction_id)
        entry = self.transactions.read(transaction_id)
        if entry is None:
            raise ObligationNotFoundError
        return self._reads(party.contact_id, [(entry, party)])[0]

    def list(self, contact_id: UUID) -> list[SettlementRead]:
        """A contact's settlements, newest first."""
        self.contacts.get(contact_id)
        rows = [r for r in self.ob.party_rows(contact_id=contact_id) if r.purpose == "settlement"]
        entries = self.transactions.read_many([r.transaction_id for r in rows])
        reads = self._reads(contact_id, [(entries[r.transaction_id], r) for r in rows if r.transaction_id in entries])
        return sorted(reads, key=lambda s: (s.date, str(s.id)), reverse=True)

    # ---- reversing ---------------------------------------------------------------------------------

    def reverse(self, transaction_id: UUID) -> None:
        """Undo a settlement for good: the obligations it cleared are owed again. Refused once what its excess left owed
        has been settled in turn."""
        party = self._party(transaction_id)
        made = self.ob.obligations(source_transaction_id=transaction_id, lock=True)
        try:
            self.netting.release([o.id for o in made])
            if self.ob.any_settled(made):
                raise ReversalBlockedError("something was settled against what this left over: reverse that first!")
            self.ob.purge(transaction_id)
            self.transactions.delete(transaction_id, commit=False)
            self.netting.even_out([party.contact_id])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
