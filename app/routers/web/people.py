"""People: the contacts the owner lends to, borrows from and shares costs with (Settings › Your data › People).

The pages are thin: every rule lives in the contact services (`services/contact.py`, `transfer.py`, `expense_sharing.py`,
`settlement.py`), the same ones the JSON API calls."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Query, Request
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import (
    Accounts,
    Categories,
    Contacts,
    ContactSummaries,
    Obligations,
    Settlements,
    SharedExpenses,
    Transfers,
)
from ...schemas.contact import (
    AllocationIn,
    ContactCreate,
    ContactRead,
    ContactUpdate,
    ObligationRead,
    SettlementCreate,
    TransferCreate,
)
from ...schemas.shared_expense import (
    ContributionIn,
    ParticipantIn,
    PaymentIn,
    SharedExpenseCreate,
)
from ...services.contact_errors import ContactNotFoundError
from ...templating import templates
from .accounts import build_tree, posting_groups, without_contacts
from .categories import category_tree
from .utils import htmx_error, htmx_redirect, parse_amount, validation_message

router = APIRouter(prefix="/people")

# The six things money can be between two people: (key, direction, purpose, what it is called, what it does).
TRANSFER_KINDS = [
    ("loan_sent", "sent", "loan", "I lent money", "They owe it back. Not spending."),
    ("borrowing_received", "received", "borrowing", "I borrowed money", "You owe it back. Not income."),
    ("advance_sent", "sent", "advance", "I paid an advance", "Money you put in for them; they owe it back."),
    ("advance_received", "received", "advance", "They paid an advance", "Money they put in for you; you owe it back."),
    ("gift_sent", "sent", "gift", "I gave a gift", "Spending under a category. Nothing is owed."),
    ("gift_received", "received", "gift", "They gave me a gift", "Income under a category. Nothing is owed."),
]
EXCESS_CHOICES = {
    "received": [("borrowing", "They lent me this"), ("advance", "An advance from them"), ("gift", "A gift")],
    "sent": [("loan", "I lent them this"), ("advance", "An advance to them"), ("gift", "A gift")],
}
SHOWS = {"all": "All", "owed": "Owe you", "owe": "You owe"}
SOURCE_NAMES = {"loan": "Loan", "borrowing": "Borrowed", "advance": "Advance"}


@dataclass
class PersonRow:
    person: ContactRead
    sub: str


def _person(contacts: Contacts, contact_id: UUID) -> ContactRead:
    found = contacts.read(contact_id)
    if found is None:
        raise HTTPException(status_code=404, detail="person not found")
    return found


def _message(error: Exception) -> str:
    return validation_message(error) if isinstance(error, ValidationError) else str(error)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value) if value else None
    except ValueError:
        return None


def money_accounts(accounts: Accounts) -> list[tuple[str, list]]:
    """The owner's own accounts that money can be kept in or paid from (never a contact's)."""
    groups = posting_groups(without_contacts(build_tree(accounts.list())))
    return [g for g in groups if g[0] in ("Assets", "Liabilities")]


def describe_obligation(o: ObligationRead) -> tuple[str, str]:
    """What an open amount is called, and the quiet line under it."""
    name = o.description or SOURCE_NAMES.get(o.source_type, "Shared expense")
    return name, "they owe you" if o.direction == "receivable" else "you owe them"


# ---- the list --------------------------------------------------------------------------------------------------


@router.get("")
def people_page(request: Request, contacts: Contacts, show: str = "all"):
    show = show if show in (*SHOWS, "archived") else "all"
    everyone = contacts.list(include_archived=True)
    live = [p for p in everyone if not p.archived]
    if show == "archived":
        chosen = [p for p in everyone if p.archived]
    elif show == "owed":
        chosen = [p for p in live if p.receivable > 0]
    elif show == "owe":
        chosen = [p for p in live if p.payable > 0]
    else:
        chosen = live
    rows = []
    for p in chosen:
        if p.archived:
            sub = "Archived"
        elif p.last_activity is None:
            sub = "Nothing yet"
        elif p.net == 0 and p.receivable == 0 and p.payable == 0:
            sub = "Settled up"
        else:
            sub = f"Last {p.last_activity.strftime('%d %b').lstrip('0')}"
        rows.append(PersonRow(p, sub))
    return templates.TemplateResponse(
        request,
        "people.html",
        {
            "active": "people",
            "show": show,
            "shows": SHOWS,
            "has_archived": any(p.archived for p in everyone),
            "rows": rows,
            "owed_total": sum((p.receivable for p in live), Decimal(0)),
            "owe_total": sum((p.payable for p in live), Decimal(0)),
            "everyone": bool(live),
        },
    )


# ---- adding and changing a person -----------------------------------------------------------------------------


@router.get("/new")
def new_person_page(request: Request):
    return templates.TemplateResponse(request, "person_form.html", {"active": "people", "person": None})


@router.post("")
def create_person(
    contacts: Contacts,
    name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    try:
        made = contacts.create(ContactCreate(name=name, email=email, phone=phone, notes=notes))
    except (ValueError, ValidationError) as e:
        return htmx_error(_message(e), "#form-error")
    return htmx_redirect(f"/people/{made.id}", flash="person-added")


@router.get("/{contact_id}/edit")
def edit_person_page(request: Request, contact_id: UUID, contacts: Contacts):
    return templates.TemplateResponse(
        request, "person_form.html", {"active": "people", "person": _person(contacts, contact_id)}
    )


@router.post("/{contact_id}/edit")
def update_person(
    contact_id: UUID,
    contacts: Contacts,
    name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
):
    _person(contacts, contact_id)
    try:
        contacts.update(contact_id, ContactUpdate(name=name, email=email, phone=phone, notes=notes))
    except (ValueError, ValidationError) as e:
        return htmx_error(_message(e), "#form-error")
    return htmx_redirect(f"/people/{contact_id}", flash="person-updated")


@router.post("/{contact_id}/archive")
def archive_person(contact_id: UUID, contacts: Contacts):
    _person(contacts, contact_id)
    try:
        contacts.archive(contact_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect("/people", flash="person-archived")


@router.post("/{contact_id}/restore")
def restore_person(contact_id: UUID, contacts: Contacts):
    _person(contacts, contact_id)
    contacts.restore(contact_id)
    return htmx_redirect(f"/people/{contact_id}", flash="person-restored")


@router.post("/{contact_id}/delete")
def delete_person(contact_id: UUID, contacts: Contacts):
    _person(contacts, contact_id)
    try:
        result = contacts.delete(contact_id)
    except ValueError as e:
        return htmx_error(str(e), "#page-error")
    return htmx_redirect("/people", flash="person-deleted" if result.outcome == "deleted" else "person-archived")


# ---- one person ------------------------------------------------------------------------------------------------


@router.get("/{contact_id}")
def person_page(
    request: Request, contact_id: UUID, contacts: Contacts, obligations: Obligations, summaries: ContactSummaries
):
    person = _person(contacts, contact_id)
    open_rows = []
    for o in obligations.list(contact_id, open_only=True):
        name, who = describe_obligation(o)
        partly = o.settled_amount > 0
        open_rows.append((o, name, who, partly))
    activity = summaries.activity(contact_id, limit=30)
    return templates.TemplateResponse(
        request,
        "person.html",
        {
            "active": "people",
            "person": person,
            "open_rows": open_rows,
            "activity": activity.items,
            "more_activity": activity.total - len(activity.items),
        },
    )


# ---- lending, borrowing and gifts ----------------------------------------------------------------------------


@router.get("/{contact_id}/transfer")
def transfer_page(request: Request, contact_id: UUID, contacts: Contacts, accounts: Accounts, categories: Categories):
    person = _person(contacts, contact_id)
    return templates.TemplateResponse(
        request,
        "person_transfer.html",
        {
            "active": "people",
            "hide_fab": True,
            "person": person,
            "kinds": TRANSFER_KINDS,
            "account_groups": money_accounts(accounts),
            "spending": category_tree(categories, "spending"),
            "earning": category_tree(categories, "earning"),
            "today": local_today().isoformat(),
        },
    )


@router.post("/{contact_id}/transfer")
def record_transfer(
    contact_id: UUID,
    transfers: Transfers,
    kind: Annotated[str, Form()] = "",
    amount: Annotated[str, Form()] = "",
    account_id: Annotated[str, Form()] = "",
    date: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    spending_category_id: Annotated[str, Form()] = "",
    earning_category_id: Annotated[str, Form()] = "",
):
    chosen = next((k for k in TRANSFER_KINDS if k[0] == kind), None)
    if chosen is None:
        return htmx_error("choose what kind of money this is.", "#form-error")
    _, direction, purpose, _, _ = chosen
    category = earning_category_id if direction == "received" else spending_category_id
    try:
        data = TransferCreate(
            direction=direction,  # pyrefly: ignore[bad-argument-type]  # one of the two
            purpose=purpose,  # pyrefly: ignore[bad-argument-type]  # one of the four
            amount=parse_amount(amount),
            account_id=_uuid(account_id),  # pyrefly: ignore[bad-argument-type]  # a missing one fails validation
            description=description,
            category_id=_uuid(category) if purpose == "gift" else None,
            **({"date": date} if date else {}),
        )
        transfers.record(contact_id, data)
    except ContactNotFoundError:
        raise HTTPException(status_code=404, detail="person not found") from None
    except (ValueError, ValidationError) as e:
        return htmx_error(_message(e), "#form-error")
    return htmx_redirect(f"/people/{contact_id}", flash="transfer-recorded")


# ---- settling up ---------------------------------------------------------------------------------------------


def _settle_data(
    direction: str,
    amount: str,
    account_id: str,
    date: str,
    description: str,
    obligation_id: str,
    excess_as: str,
    excess_category_id: str,
) -> SettlementCreate:
    manual = _uuid(obligation_id)
    value = parse_amount(amount)
    return SettlementCreate(
        direction=direction,  # pyrefly: ignore[bad-argument-type]  # checked by the schema
        amount=value,
        account_id=_uuid(account_id),  # pyrefly: ignore[bad-argument-type]  # a missing one fails validation
        allocation_method="manual" if manual else "fifo",
        allocations=[AllocationIn(obligation_id=manual, amount=value)] if manual else [],
        description=description,
        excess_as=excess_as or None,  # pyrefly: ignore[bad-argument-type]  # checked by the schema
        excess_category_id=_uuid(excess_category_id),
        **({"date": date} if date else {}),
    )


@router.get("/{contact_id}/settle")
def settle_page(
    request: Request,
    contact_id: UUID,
    contacts: Contacts,
    obligations: Obligations,
    accounts: Accounts,
    obligation: str = "",
):
    person = _person(contacts, contact_id)
    chosen: ObligationRead | None = None
    if obligation_id := _uuid(obligation):
        found = [o for o in obligations.list(contact_id, open_only=True) if o.id == obligation_id]
        chosen = found[0] if found else None
    if chosen is not None:
        direction, amount = ("received" if chosen.direction == "receivable" else "sent"), chosen.outstanding_amount
    else:
        direction = "received" if person.receivable > 0 or person.payable == 0 else "sent"
        amount = person.receivable if direction == "received" else person.payable
    return templates.TemplateResponse(
        request,
        "person_settle.html",
        {
            "active": "people",
            "hide_fab": True,
            "person": person,
            "direction": direction,
            "amount": amount if amount > 0 else "",
            "chosen": chosen,
            "account_groups": money_accounts(accounts),
            "today": local_today().isoformat(),
        },
    )


@router.post("/{contact_id}/settle/preview")
def settle_preview(
    request: Request,
    contact_id: UUID,
    settlements: Settlements,
    obligations: Obligations,
    contacts: Contacts,
    direction: Annotated[str, Form()] = "received",
    amount: Annotated[str, Form()] = "",
    account_id: Annotated[str, Form()] = "",
    date: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    obligation_id: Annotated[str, Form()] = "",
    excess_as: Annotated[str, Form()] = "",
    excess_category_id: Annotated[str, Form()] = "",
):
    _person(contacts, contact_id)
    context: dict[str, Any] = {
        "direction": direction,
        "preview": None,
        "message": None,
        "excess_as": excess_as,
        "excess_choices": EXCESS_CHOICES.get(direction, []),
        "names": {o.id: describe_obligation(o)[0] for o in obligations.list(contact_id)},
    }
    if amount.strip():
        try:
            data = _settle_data(
                direction, amount, account_id or str(UUID(int=0)), date, description, obligation_id, excess_as, ""
            )
            context["preview"] = settlements.preview(contact_id, data)
        except ContactNotFoundError:
            raise HTTPException(status_code=404, detail="person not found") from None
        except (ValueError, ValidationError) as e:
            context["message"] = _message(e)
    return templates.TemplateResponse(request, "partials/settle_preview.html", context)


@router.post("/{contact_id}/settle")
def record_settlement(
    contact_id: UUID,
    settlements: Settlements,
    direction: Annotated[str, Form()] = "received",
    amount: Annotated[str, Form()] = "",
    account_id: Annotated[str, Form()] = "",
    date: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    obligation_id: Annotated[str, Form()] = "",
    excess_as: Annotated[str, Form()] = "",
    excess_category_id: Annotated[str, Form()] = "",
):
    try:
        data = _settle_data(
            direction, amount, account_id, date, description, obligation_id, excess_as, excess_category_id
        )
        settlements.record(contact_id, data)
    except ContactNotFoundError:
        raise HTTPException(status_code=404, detail="person not found") from None
    except (ValueError, ValidationError) as e:
        return htmx_error(_message(e), "#form-error")
    return htmx_redirect(f"/people/{contact_id}", flash="settled-up")


# ---- sharing a bill ---------------------------------------------------------------------------------------------


@router.get("/expense/new")
def expense_page(
    request: Request,
    contacts: Contacts,
    accounts: Accounts,
    categories: Categories,
    with_person: Annotated[str, Query(alias="with")] = "",
):
    people = contacts.list()
    start = _uuid(with_person)
    return templates.TemplateResponse(
        request,
        "person_expense.html",
        {
            "active": "people",
            "hide_fab": True,
            "people": people,
            "start": start,
            "back": f"/people/{start}" if start else "/people",
            "account_groups": money_accounts(accounts),
            "spending": category_tree(categories, "spending"),
            "today": local_today().isoformat(),
            "methods": [("equal", "Equally"), ("exact", "Amounts"), ("percentage", "%"), ("shares", "Shares")],
        },
    )


def _expense_data(form: dict[str, str], people: list[ContactRead]) -> SharedExpenseCreate:
    """The shared expense a form describes. A box left empty is not given: your own payment is whatever the others
    did not pay."""
    method = form.get("split_method", "equal")
    total = parse_amount(form.get("total_amount"))

    def value(key: str) -> Decimal | None:
        raw = (form.get(key) or "").strip()
        return parse_amount(raw) if raw else None

    chosen = [p for p in people if form.get(f"with_{p.id}")]
    participants = [ParticipantIn(is_self=True, value=value("value_self") if method != "equal" else None)] + [
        ParticipantIn(contact_id=p.id, value=value(f"value_{p.id}") if method != "equal" else None) for p in chosen
    ]
    contributions = [
        ContributionIn(contact_id=p.id, amount=paid)
        for p in chosen
        if (paid := value(f"paid_{p.id}")) is not None and paid > 0
    ]
    mine = value("paid_self")
    if mine is None:
        mine = total - sum((c.amount for c in contributions), Decimal(0))
    account = _uuid(form.get("account_id", ""))
    payments = [PaymentIn(account_id=account, amount=mine)] if mine > 0 and account else []
    if mine > 0 and not account:
        raise ValueError("choose the account you paid from!")
    extra = {"date": form["date"]} if form.get("date") else {}
    return SharedExpenseCreate(
        description=form.get("description", ""),
        total_amount=total,
        category_id=_uuid(form.get("category_id", "")),
        split_method=method,  # pyrefly: ignore[bad-argument-type]  # checked by the schema
        participants=participants,
        contributions=contributions,
        payments=payments,
        **extra,
    )


@router.post("/expense/preview")
async def expense_preview(request: Request, contacts: Contacts, expenses: SharedExpenses):
    form = {k: str(v) for k, v in (await request.form()).items()}
    context: dict[str, Any] = {"preview": None, "message": None}
    if form.get("total_amount", "").strip():
        try:
            context["preview"] = expenses.preview(_expense_data(form, contacts.list()))
        except (ValueError, ValidationError) as e:
            context["message"] = _message(e)
    return templates.TemplateResponse(request, "partials/expense_preview.html", context)


@router.post("/expense")
async def record_expense(request: Request, contacts: Contacts, expenses: SharedExpenses):
    form = {k: str(v) for k, v in (await request.form()).items()}
    try:
        made = expenses.create(_expense_data(form, contacts.list()), confirm=True)
    except (ValueError, ValidationError) as e:
        return htmx_error(_message(e), "#form-error")
    start = _uuid(form.get("back_to", ""))
    other = next((s.contact_id for s in made.shares if s.contact_id), None)
    return htmx_redirect(f"/people/{start or other}" if start or other else "/people", flash="expense-shared")


# ---- an entry in the activity: what it was, and undoing it ---------------------------------------------------


@router.get("/{contact_id}/entry/{transaction_id}/sheet")
def entry_sheet(
    request: Request,
    contact_id: UUID,
    transaction_id: UUID,
    contacts: Contacts,
    summaries: ContactSummaries,
):
    person = _person(contacts, contact_id)
    found = [i for i in summaries.activity(contact_id, limit=200).items if i.transaction_id == transaction_id]
    if not found:
        raise HTTPException(status_code=404, detail="entry not found")
    return templates.TemplateResponse(request, "partials/person_entry_sheet.html", {"person": person, "item": found[0]})


@router.post("/{contact_id}/entry/{transaction_id}/reverse")
def reverse_entry(
    contact_id: UUID,
    transaction_id: UUID,
    contacts: Contacts,
    summaries: ContactSummaries,
    transfers: Transfers,
    settlements: Settlements,
    expenses: SharedExpenses,
):
    _person(contacts, contact_id)
    found = [i for i in summaries.activity(contact_id, limit=200).items if i.transaction_id == transaction_id]
    if not found:
        raise HTTPException(status_code=404, detail="entry not found")
    try:
        if found[0].purpose == "settlement":
            settlements.reverse(transaction_id)
        elif found[0].purpose == "expense":
            expense = next((e for e in expenses.list("confirmed") if e.transaction_id == transaction_id), None)
            if expense is None:
                raise ValueError("shared expense not found!")
            expenses.cancel(expense.id)
        else:
            transfers.reverse(transaction_id)
    except ValueError as e:
        return htmx_error(str(e), "#person-sheet-error")
    return htmx_redirect(f"/people/{contact_id}", flash="entry-reversed")
