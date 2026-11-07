"""Expenses shared with contacts.

An expense is planned as a draft (who shares it, how, and who paid what) and confirmed into one ordinary ledger entry:

- your own share is spent (a debit to Expenses under the expense's category), so only that counts against your budget;
- what you paid leaves the accounts you name (credits);
- each contact is settled against their own payment: one who paid less than their share owes you (debit "Due from X"
  for the difference), one who paid more is owed (credit "Due to X"). A contact's payment never touches your accounts.

Every difference becomes an obligation of that one contact; nobody owes a third contact. The entry balances because the
shares and the payments both add up to the total, which confirming insists on (a bill that is not fully paid for stays
a draft)."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from ..models.contact import ExpenseContribution, ExpenseShare, SharedExpense
from ..models.transaction import PostingSide
from ..repositories.obligation import ObligationRepository
from ..repositories.shared_expense import SharedExpenseRepository
from ..schemas.shared_expense import (
    ContributionRead,
    ExpensePreview,
    LineRead,
    OwedRead,
    ParticipantIn,
    SharedExpenseCreate,
    SharedExpenseRead,
    SharedExpenseUpdate,
    ShareRead,
)
from ..schemas.transaction import PostingCreate, TransactionCreate
from .contact import PAYABLE, RECEIVABLE, ContactService
from .contact_errors import (
    DuplicateRequestError,
    InvalidExpenseAllocationError,
    InvalidExpenseContributionError,
    ReversalBlockedError,
    SharedExpenseAlreadyConfirmedError,
    SharedExpenseNotFoundError,
)
from .splits import split
from .transaction import TransactionService, decimal_places

ZERO = Decimal(0)


@dataclass
class _Person:
    contact_id: UUID | None  # none for the owner
    name: str
    share: Decimal
    value: Decimal | None
    paid: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.paid - self.share


@dataclass
class _Plan:
    description: str
    total: Decimal
    date: object
    category_id: UUID | None
    method: str
    people: list[_Person]
    payments: list[tuple[UUID, Decimal]]  # the owner's payments: (account, amount)


class ExpenseSharingService:
    def __init__(
        self,
        contacts: ContactService,
        transactions: TransactionService,
        ob: ObligationRepository,
        er: SharedExpenseRepository,
    ):
        self.contacts = contacts
        self.transactions = transactions  # made with contacts=True
        self.ob = ob
        self.er = er
        self.db = er.db

    # ---- working out a plan ------------------------------------------------------------------------

    @staticmethod
    def _owner(plan: _Plan) -> _Person:
        return next(p for p in plan.people if p.contact_id is None)

    def _plan(self, data: SharedExpenseCreate) -> _Plan:
        """Check a request and work the shares out. Raises what is wrong; funding is not checked here (a draft may be
        part-paid)."""
        places = self.transactions.currency().decimals
        if decimal_places(data.total_amount) > places:
            raise InvalidExpenseAllocationError(f"amounts can have at most {places} decimal places!")
        if data.category_id is not None:
            found = next((c for c in self.transactions.cr.list() if c.id == data.category_id), None)
            if found is None or found.kind != "spending":
                raise InvalidExpenseAllocationError("the category must be one of your spending categories!")
            if found.closed_on is not None:
                raise InvalidExpenseAllocationError(f"category '{found.name}' is closed: reopen it to use it!")
        owners = [p for p in data.participants if p.is_self]
        if len(owners) != 1:
            raise InvalidExpenseAllocationError("you (is_self) must be one of the participants, once!")
        ids = [p.contact_id for p in data.participants if p.contact_id is not None]
        if len(set(ids)) != len(ids):
            raise InvalidExpenseAllocationError("a contact is listed twice!")
        names = {c.id: c.name for c in self.contacts.cr.list()}
        for contact_id in ids:
            self.contacts.active(contact_id)
        values = [p.value for p in data.participants]
        shares = split(data.total_amount, data.split_method, values, places)
        people = [
            _Person(
                contact_id=p.contact_id,
                name="You" if p.is_self else names[p.contact_id],  # pyrefly: ignore[bad-index]  # checked active above
                share=share,
                value=p.value if data.split_method != "equal" else None,
            )
            for p, share in zip(data.participants, shares, strict=True)
        ]
        by_contact = {p.contact_id: p for p in people}
        seen: set[UUID] = set()
        for paid in data.contributions:
            if paid.contact_id not in by_contact:
                raise InvalidExpenseContributionError("a contact who paid must be one of the participants!")
            if paid.contact_id in seen:
                raise InvalidExpenseContributionError("a contact is listed twice among the payments!")
            if decimal_places(paid.amount) > places:
                raise InvalidExpenseContributionError(f"amounts can have at most {places} decimal places!")
            seen.add(paid.contact_id)
            by_contact[paid.contact_id].paid = paid.amount
        accounts: set[UUID] = set()
        payments: list[tuple[UUID, Decimal]] = []
        for payment in data.payments:
            account_id = self.contacts.own_account(payment.account_id)
            if account_id in accounts:
                raise InvalidExpenseContributionError("an account is listed twice among your payments!")
            if decimal_places(payment.amount) > places:
                raise InvalidExpenseContributionError(f"amounts can have at most {places} decimal places!")
            accounts.add(account_id)
            payments.append((account_id, payment.amount))
        by_contact[None].paid = sum((amount for _, amount in payments), ZERO)
        return _Plan(
            data.description, data.total_amount, data.date, data.category_id, data.split_method, people, payments
        )

    def _lines(self, plan: _Plan) -> list[PostingCreate]:
        """The ledger lines (see the module note); they balance because shares and payments both add up to the total."""
        roots = {a.name: a.id for a in self.contacts.accounts.ar.list() if a.parent_id is None}
        owner = self._owner(plan)
        lines: list[PostingCreate] = []
        if owner.share > 0:
            lines.append(
                PostingCreate(
                    account_id=roots["Expenses"],
                    side=PostingSide.DEBIT,
                    amount=owner.share,
                    category_id=plan.category_id,
                )
            )
        lines += [
            PostingCreate(account_id=account_id, side=PostingSide.CREDIT, amount=amount)
            for account_id, amount in plan.payments
        ]
        for person in plan.people:
            if person.contact_id is None or person.net == 0:
                continue
            ids = self.contacts.account_ids(person.contact_id)
            if person.net < 0:  # paid less than their share: they owe the owner
                lines.append(PostingCreate(account_id=ids[RECEIVABLE], side=PostingSide.DEBIT, amount=-person.net))
            else:  # paid more: the owner owes them
                lines.append(PostingCreate(account_id=ids[PAYABLE], side=PostingSide.CREDIT, amount=person.net))
        return lines

    def _describe(self, plan: _Plan) -> ExpensePreview:
        owner = self._owner(plan)
        funded = sum((p.paid for p in plan.people), ZERO)
        unfunded = plan.total - funded
        lines = self._lines(plan) if unfunded == 0 and plan.total > 0 else []
        owed = [
            OwedRead(
                contact_id=p.contact_id,
                name=p.name,
                direction="receivable" if p.net < 0 else "payable",
                amount=abs(p.net),
            )
            for p in plan.people
            if p.contact_id is not None and p.net != 0
        ]
        return ExpensePreview(
            description=plan.description,
            total_amount=plan.total,
            date=plan.date,  # pyrefly: ignore[bad-argument-type]  # always a day
            category_id=plan.category_id,
            split_method=plan.method,  # pyrefly: ignore[bad-argument-type]  # checked by the schema
            user_share=owner.share,
            user_paid=owner.paid,
            funded=funded,
            unfunded=unfunded,
            shares=[
                ShareRead(
                    is_self=p.contact_id is None,
                    contact_id=p.contact_id,
                    name=p.name,
                    share_amount=p.share,
                    share_value=p.value,
                    contributed=p.paid,
                    net=p.net,
                )
                for p in plan.people
            ],
            contributions=[
                *(ContributionRead(is_self=True, contact_id=None, account_id=a, amount=m) for a, m in plan.payments),
                *(
                    ContributionRead(is_self=False, contact_id=p.contact_id, account_id=None, amount=p.paid)
                    for p in plan.people
                    if p.contact_id is not None and p.paid > 0
                ),
            ],
            lines=[
                LineRead(account_id=line.target, category_id=line.category_id, side=line.side, amount=line.amount)
                for line in lines
            ],
            owed=owed,
        )

    def preview(self, data: SharedExpenseCreate) -> ExpensePreview:
        """What the expense would do, saving nothing."""
        return self._describe(self._plan(data))

    # ---- storing a draft ---------------------------------------------------------------------------

    def _store(self, expense: SharedExpense, plan: _Plan) -> None:
        self.er.clear_children(expense.id)
        for person in plan.people:
            self.db.add(
                ExpenseShare(
                    user_id=self.er.uid,
                    shared_expense_id=expense.id,
                    contact_id=person.contact_id,
                    is_self=person.contact_id is None,
                    share_amount=person.share,
                    share_value=person.value,
                )
            )
            if person.contact_id is not None and person.paid > 0:
                self.db.add(
                    ExpenseContribution(
                        user_id=self.er.uid,
                        shared_expense_id=expense.id,
                        contact_id=person.contact_id,
                        amount=person.paid,
                    )
                )
        for account_id, amount in plan.payments:
            self.db.add(
                ExpenseContribution(
                    user_id=self.er.uid,
                    shared_expense_id=expense.id,
                    is_self=True,
                    account_id=account_id,
                    amount=amount,
                )
            )
        self.db.flush()

    def _data_of(self, expense: SharedExpense) -> SharedExpenseCreate:
        """The request that would make this expense again (from its stored shares and payments)."""
        shares = self.er.shares(expense.id)
        paid = self.er.contributions(expense.id)
        return SharedExpenseCreate(
            description=expense.description,
            total_amount=expense.total_amount,
            date=expense.date,
            category_id=expense.category_id,
            split_method=expense.split_method,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
            participants=[
                ParticipantIn(
                    is_self=s.is_self,
                    contact_id=s.contact_id,
                    value=s.share_value if expense.split_method != "equal" else None,
                )
                for s in shares
            ],
            contributions=[{"contact_id": c.contact_id, "amount": c.amount} for c in paid if not c.is_self],  # pyrefly: ignore[bad-argument-type]
            payments=[{"account_id": c.account_id, "amount": c.amount} for c in paid if c.is_self],  # pyrefly: ignore[bad-argument-type]
        )

    # ---- reading -----------------------------------------------------------------------------------

    def _get(self, expense_id: UUID, lock: bool = False) -> SharedExpense:
        expense = self.er.read(expense_id, lock=lock)
        if expense is None:
            raise SharedExpenseNotFoundError
        return expense

    def _read(self, expense: SharedExpense) -> SharedExpenseRead:
        preview = self._describe(self._plan_of(expense))
        return SharedExpenseRead(
            **preview.model_dump(),
            id=expense.id,
            status=expense.status,  # pyrefly: ignore[bad-argument-type]  # a database CHECK limits it
            transaction_id=expense.transaction_id,
        )

    def _plan_of(self, expense: SharedExpense) -> _Plan:
        """The stored plan, with the shares as they were worked out then (not worked out again)."""
        names = {c.id: c.name for c in self.contacts.cr.list()}
        people = [
            _Person(
                contact_id=s.contact_id,
                name="You" if s.is_self else names[s.contact_id],  # pyrefly: ignore[bad-index]
                share=s.share_amount,
                value=s.share_value,
            )
            for s in self.er.shares(expense.id)
        ]
        by_contact = {p.contact_id: p for p in people}
        payments = []
        for c in self.er.contributions(expense.id):
            by_contact[c.contact_id].paid += c.amount
            if c.is_self:
                payments.append((c.account_id, c.amount))
        return _Plan(
            expense.description,
            expense.total_amount,
            expense.date,
            expense.category_id,
            expense.split_method,
            people,
            payments,  # pyrefly: ignore[bad-argument-type]  # own payments always name an account
        )

    def read(self, expense_id: UUID) -> SharedExpenseRead:
        return self._read(self._get(expense_id))

    def list(self, status: str | None = None) -> list[SharedExpenseRead]:
        return [self._read(e) for e in self.er.list(status)]

    # ---- writing -----------------------------------------------------------------------------------

    def create(self, data: SharedExpenseCreate, confirm: bool = False, key: str | None = None) -> SharedExpenseRead:
        """Save a draft; with `confirm` also record it, all in one commit."""
        if confirm and key and (found := self.ob.request(key)) is not None:
            return self._replay(found.transaction_id, data)
        plan = self._plan(data)
        try:
            expense = self.er.add(
                SharedExpense(
                    user_id=self.er.uid,
                    description=plan.description,
                    date=plan.date,  # pyrefly: ignore[bad-argument-type]
                    total_amount=plan.total,
                    category_id=plan.category_id,
                    split_method=plan.method,
                )
            )
            self._store(expense, plan)
            if confirm:
                self._confirm(expense, key)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(expense)

    def _replay(self, transaction_id: UUID, data: SharedExpenseCreate) -> SharedExpenseRead:
        found = self.er.by_transaction(transaction_id)
        if found is None:
            raise DuplicateRequestError("this idempotency key was already used for a different request!")
        read = self._read(found)
        if (read.description, read.total_amount, read.date) != (data.description, data.total_amount, data.date):
            raise DuplicateRequestError("this idempotency key was already used for a different request!")
        return read

    def update(self, expense_id: UUID, data: SharedExpenseUpdate) -> SharedExpenseRead:
        expense = self._get(expense_id, lock=True)
        if expense.status == "confirmed":
            raise SharedExpenseAlreadyConfirmedError(
                "a confirmed shared expense can't be edited: cancel it and enter it again!"
            )
        current = self._data_of(expense).model_dump()
        current.update(data.model_dump(exclude_unset=True))
        plan = self._plan(SharedExpenseCreate.model_validate(current))
        try:
            expense.description, expense.date, expense.total_amount = plan.description, plan.date, plan.total  # pyrefly: ignore[bad-assignment]
            expense.category_id, expense.split_method = plan.category_id, plan.method
            self.db.add(expense)
            self._store(expense, plan)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(expense)

    def _confirm(self, expense: SharedExpense, key: str | None) -> None:
        """Record the ledger entry and everything about it (the caller commits)."""
        plan = self._plan_of(expense)
        for person in plan.people:
            if person.contact_id is not None:
                self.contacts.active(person.contact_id)
        for account_id, _ in plan.payments:
            self.contacts.own_account(account_id)
        described = self._describe(plan)
        if described.unfunded != 0:
            raise InvalidExpenseContributionError(
                f"the payments add up to {described.funded:f}, not the total {plan.total:f}: "
                "say who paid the rest before confirming!"
            )
        lines = self._lines(plan)
        if len(lines) < 2:
            raise InvalidExpenseAllocationError("nothing is owed and nothing is spent: there is no entry to record!")
        entry = self.transactions.create(
            TransactionCreate(
                date=expense.date,
                payee=expense.description,
                postings=lines,
            ),
            commit=False,
        )
        for person in plan.people:
            if person.contact_id is None:
                continue
            self.ob.add_party(person.contact_id, entry.id, "expense", "received" if person.net > 0 else "sent")
            if person.net != 0:
                self.ob.add_obligation(
                    person.contact_id,
                    entry.id,
                    "shared_expense",
                    "receivable" if person.net < 0 else "payable",
                    abs(person.net),
                )
        expense.transaction_id, expense.status = entry.id, "confirmed"
        self.db.add(expense)
        if key:
            self.ob.add_request(key, entry.id)
        self.db.flush()

    def confirm(self, expense_id: UUID, key: str | None = None) -> SharedExpenseRead:
        """Record a draft: the ledger entry, what each contact owes or is owed, and their activity."""
        if key and (found := self.ob.request(key)) is not None:
            replayed = self.er.by_transaction(found.transaction_id)
            if replayed is not None and replayed.id == expense_id:
                return self._read(replayed)
            raise DuplicateRequestError("this idempotency key was already used for a different request!")
        expense = self._get(expense_id, lock=True)
        if expense.status == "confirmed":
            raise SharedExpenseAlreadyConfirmedError("this shared expense is already confirmed!")
        try:
            self._confirm(expense, key)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(expense)

    def cancel(self, expense_id: UUID) -> None:
        """Remove a draft, or reverse a confirmed expense for good (its entry and what it left owed go too). A
        confirmed one is refused once anything was settled against what it left owed."""
        expense = self._get(expense_id, lock=True)
        entry_id = expense.transaction_id
        try:
            if entry_id is not None:
                obligations = self.ob.obligations(source_transaction_id=entry_id, lock=True)
                if any(self.ob.settled([o.id]).get(o.id) for o in obligations):
                    raise ReversalBlockedError("something was settled against this: reverse the settlement first!")
            self.er.delete(expense)
            if entry_id is not None:
                self.ob.purge(entry_id)
                self.transactions.delete(entry_id, commit=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
