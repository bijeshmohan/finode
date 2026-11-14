"""A bill or an income shared with people, as the Add screen's Split describes it (the web form and /api/entries
alike), turned into what the sharing services record, and back into the form's starting values for an edit.

The rules are the form's: a box left empty is not given. Your own payment on a bill is whatever the others did not
pay; what landed in your account from an income is whatever the people did not receive for you."""

from collections.abc import Set
from decimal import Decimal
from uuid import UUID

from ..schemas.entry import EntryForm, ExpenseShare, IncomePart, IncomeShare, PersonShare
from ..schemas.shared_expense import ContributionIn, ParticipantIn, PaymentIn, SharedExpenseCreate, SharedExpenseRead
from ..schemas.shared_income import IncomeDepositIn, IncomePartIn, SharedIncomeCreate, SharedIncomeRead


def _total(form: EntryForm) -> Decimal:
    if form.total is None:
        raise ValueError("amount is required!")
    return form.total


def _check_people(ids: list[UUID], people: Set[UUID]) -> None:
    """Only the person's own contacts can share a bill or an income."""
    if any(i not in people for i in ids):
        raise ValueError("person not found")


def _dated(form: EntryForm) -> dict:
    return {"date": form.date} if form.date else {}


def expense_create(form: EntryForm, share: ExpenseShare, people: Set[UUID]) -> SharedExpenseCreate:
    """The shared bill the form describes. `people` are the person's own contacts."""
    _check_people([p.contact_id for p in share.people], people)
    total = _total(form)
    valued = share.method != "equal"
    participants = [ParticipantIn(is_self=True, value=share.self_value if valued else None)] + [
        ParticipantIn(contact_id=p.contact_id, value=p.value if valued else None) for p in share.people
    ]
    contributions = [
        ContributionIn(contact_id=p.contact_id, amount=p.paid) for p in share.people if p.paid is not None and p.paid > 0
    ]
    mine = share.self_paid
    if mine is None:
        mine = total - sum((c.amount for c in contributions), Decimal(0))
    if mine > 0 and not share.account_id:
        raise ValueError("choose the account you paid from!")
    payments = [PaymentIn(account_id=share.account_id, amount=mine)] if mine > 0 and share.account_id else []
    return SharedExpenseCreate(
        description=(form.payee or "").strip() or "Shared bill",
        total_amount=total,
        category_id=share.category_id,
        split_method=share.method,
        participants=participants,
        contributions=contributions,
        payments=payments,
        **_dated(form),
    )


def income_create(form: EntryForm, share: IncomeShare, people: Set[UUID]) -> SharedIncomeCreate:
    """The shared income the form describes. `people` are the person's own contacts."""
    _check_people([p.contact_id for p in share.people], people)
    total = _total(form)
    theirs = [
        IncomePartIn(contact_id=p.contact_id, amount=p.theirs)
        for p in share.people
        if p.theirs is not None and p.theirs > 0
    ]
    got = [
        IncomePartIn(contact_id=p.contact_id, amount=p.received)
        for p in share.people
        if p.received is not None and p.received > 0
    ]
    landed = total - sum((g.amount for g in got), Decimal(0))
    if landed > 0 and not share.account_id:
        raise ValueError("choose the account it was paid into!")
    deposits = [IncomeDepositIn(account_id=share.account_id, amount=landed)] if landed > 0 and share.account_id else []
    return SharedIncomeCreate(
        description=(form.payee or "").strip() or "Shared income",
        total_amount=total,
        category_id=share.category_id,
        theirs=theirs,
        received_by=got,
        deposits=deposits,
        **_dated(form),
    )


def expense_start(bill: SharedExpenseRead | None, with_id: UUID | None = None) -> ExpenseShare:
    """What the Split editor starts with: the shared bill being edited, or one person ticked (opened from their
    page)."""
    if bill is None:
        return ExpenseShare(people=[PersonShare(contact_id=with_id)] if with_id else [])
    valued = bill.split_method != "equal"
    shares = {s.contact_id: s for s in bill.shares}
    paid = {c.contact_id: c.amount for c in bill.contributions if not c.is_self}
    mine = shares.get(None)
    return ExpenseShare(
        category_id=bill.category_id,
        account_id=next((c.account_id for c in bill.contributions if c.is_self), None),
        method=bill.split_method,
        self_value=mine.share_value if valued and mine else None,
        # Said only when someone else paid too: otherwise it is simply the rest.
        self_paid=sum((c.amount for c in bill.contributions if c.is_self), Decimal(0)) if paid else None,
        people=[
            PersonShare(
                contact_id=contact_id,
                value=s.share_value if valued else None,
                paid=paid.get(contact_id),
            )
            for contact_id, s in shares.items()
            if contact_id is not None
        ],
    )


def income_start(shared: SharedIncomeRead | None) -> IncomeShare:
    """What the income Split editor starts with: the shared income being edited, or nothing."""
    if shared is None:
        return IncomeShare()
    theirs = {p.contact_id: p.amount for p in shared.theirs}
    received = {p.contact_id: p.amount for p in shared.received_by}
    return IncomeShare(
        category_id=shared.category_id,
        account_id=next((d.account_id for d in shared.deposits), None),
        people=[
            IncomePart(contact_id=c, theirs=theirs.get(c), received=received.get(c)) for c in {**theirs, **received}
        ],
    )
