"""People: the contacts the owner lends to, borrows from and shares costs with (Settings › Your data › People).

The pages are thin: every rule lives in the contact services (`services/contact.py`, `transfer.py`, `expense_sharing.py`,
`settlement.py`), the same ones the JSON API calls."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import (
    Accounts,
    Contacts,
    ContactSummaries,
    Obligations,
    Settlements,
    SharedExpenses,
    SharedIncomes,
    Transfers,
)
from ...schemas.contact import (
    ContactCreate,
    ContactRead,
    ContactUpdate,
    ObligationRead,
    OpeningBalanceCreate,
    OpeningBalanceUpdate,
)
from ...schemas.shared_expense import (
    ContributionIn,
    ParticipantIn,
    PaymentIn,
    SharedExpenseCreate,
)
from ...schemas.shared_income import IncomeDepositIn, IncomePartIn, SharedIncomeCreate
from ...templating import grouping_for, money, templates
from .accounts import build_tree, posting_groups, without_contacts
from .utils import htmx_error, htmx_redirect, parse_amount, validation_message

router = APIRouter(prefix="/people")

SHOWS = {"all": "All", "owed": "Owe you", "owe": "You owe"}
SOURCE_NAMES = {"loan": "Loan", "borrowing": "Borrowed", "advance": "Advance", "opening": "Opening balance"}


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
        elif p.net == 0:
            sub = f"Even · {money(p.receivable, grouping_for(request.state.currency))} each way"
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
            "currency": request.state.currency,
        },
    )


# ---- adding and changing a person -----------------------------------------------------------------------------


@router.get("/new")
def new_person_page(request: Request):
    return templates.TemplateResponse(
        request, "person_form.html", {"active": "people", "person": None, "today": local_today().isoformat()}
    )


def _opening(direction: str, amount: str, since: str, description: str = "") -> OpeningBalanceCreate | None:
    """The opening balance a form describes, or none when the amount is left empty."""
    if not amount.strip():
        return None
    return OpeningBalanceCreate(
        direction="payable" if direction == "payable" else "receivable",
        amount=parse_amount(amount),
        description=description,
        **({"date": since} if since else {}),
    )


@router.post("")
def create_person(
    contacts: Contacts,
    transfers: Transfers,
    name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    opening_direction: Annotated[str, Form()] = "receivable",
    opening_amount: Annotated[str, Form()] = "",
    opening_since: Annotated[str, Form()] = "",
):
    try:
        opening = _opening(opening_direction, opening_amount, opening_since)  # checked before anyone is made
        made = contacts.create(ContactCreate(name=name, email=email, phone=phone, notes=notes))
    except (ValueError, ValidationError) as e:
        return htmx_error(_message(e), "#form-error")
    if opening is not None:
        try:
            transfers.opening_balance(made.id, opening)
        except (ValueError, ValidationError) as e:
            contacts.delete(made.id)  # nothing else was done with them: they are removed again, not left half made
            return htmx_error(_message(e), "#form-error")
    return htmx_redirect(f"/people/{made.id}", flash="person-added")


@router.get("/{contact_id}/opening")
def opening_page(request: Request, contact_id: UUID, contacts: Contacts):
    return templates.TemplateResponse(
        request,
        "person_opening.html",
        {
            "active": "people",
            "hide_fab": True,
            "person": _person(contacts, contact_id),
            "today": local_today().isoformat(),
        },
    )


@router.post("/{contact_id}/opening")
def add_opening(
    contact_id: UUID,
    contacts: Contacts,
    transfers: Transfers,
    opening_direction: Annotated[str, Form()] = "receivable",
    opening_amount: Annotated[str, Form()] = "",
    opening_since: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
):
    _person(contacts, contact_id)
    try:
        opening = _opening(opening_direction, opening_amount, opening_since, description)
        if opening is None:
            raise ValueError("enter the amount!")
        transfers.opening_balance(contact_id, opening)
    except (ValueError, ValidationError) as e:
        return htmx_error(_message(e), "#form-error")
    return htmx_redirect(f"/people/{contact_id}", flash="opening-added")


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
            "currency": request.state.currency,
        },
    )


@router.get("/{contact_id}/opening/{transaction_id}/edit")
def edit_opening_page(
    request: Request,
    contact_id: UUID,
    transaction_id: UUID,
    contacts: Contacts,
    transfers: Transfers,
    obligations: Obligations,
):
    person = _person(contacts, contact_id)
    try:
        found = transfers.read(transaction_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="entry not found") from None
    if found.purpose != "opening" or found.contact_id != contact_id:
        raise HTTPException(status_code=404, detail="entry not found")
    mine = next(o for o in obligations.list(contact_id) if o.id == found.obligation_id)
    return templates.TemplateResponse(
        request,
        "person_opening.html",
        {
            "active": "people",
            "hide_fab": True,
            "person": person,
            "today": found.date.isoformat(),
            "editing": found,
            "direction": mine.direction,
            "paid": mine.settled_amount,
            "currency": request.state.currency,
        },
    )


@router.post("/{contact_id}/opening/{transaction_id}/edit")
def change_opening(
    contact_id: UUID,
    transaction_id: UUID,
    contacts: Contacts,
    transfers: Transfers,
    opening_direction: Annotated[str, Form()] = "receivable",
    opening_amount: Annotated[str, Form()] = "",
    opening_since: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
):
    _person(contacts, contact_id)
    try:
        if transfers.read(transaction_id).contact_id != contact_id:
            raise HTTPException(status_code=404, detail="entry not found")
        changes = OpeningBalanceUpdate(
            direction="payable" if opening_direction == "payable" else "receivable",
            amount=parse_amount(opening_amount),
            date=opening_since or None,  # pyrefly: ignore[bad-argument-type]  # parsed by the schema
            description=description,
        )
        transfers.update_opening(transaction_id, changes)
    except HTTPException:
        raise
    except (ValueError, ValidationError) as e:
        return htmx_error(_message(e), "#form-error")
    return htmx_redirect(f"/people/{contact_id}", flash="opening-updated")


# ---- sharing a bill ---------------------------------------------------------------------------------------------


def expense_data(form: dict[str, str], people: Sequence) -> SharedExpenseCreate:
    """The shared expense a form describes. A box left empty is not given: your own payment is whatever the others
    did not pay."""
    method = form.get("split_method", "equal")
    total = parse_amount(form.get("total_amount") or form.get("total"))

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
        description=(form.get("description") or form.get("payee") or "").strip() or "Shared bill",
        total_amount=total,
        category_id=_uuid(form.get("category_id", "")),
        split_method=method,  # pyrefly: ignore[bad-argument-type]  # checked by the schema
        participants=participants,
        contributions=contributions,
        payments=payments,
        **extra,
    )


def income_data(form: dict[str, str], people: Sequence) -> SharedIncomeCreate:
    """The shared income a form describes. A box left empty is not given: what landed in your account is whatever the
    people did not receive."""
    total = parse_amount(form.get("total_amount") or form.get("total"))

    def value(key: str) -> Decimal | None:
        raw = (form.get(key) or "").strip()
        return parse_amount(raw) if raw else None

    theirs = [
        IncomePartIn(contact_id=p.id, amount=v) for p in people if (v := value(f"theirs_{p.id}")) is not None and v > 0
    ]
    got = [IncomePartIn(contact_id=p.id, amount=v) for p in people if (v := value(f"got_{p.id}")) is not None and v > 0]
    landed = total - sum((g.amount for g in got), Decimal(0))
    account = _uuid(form.get("income_account_id", ""))
    if landed > 0 and not account:
        raise ValueError("choose the account it was paid into!")
    extra = {"date": form["date"]} if form.get("date") else {}
    return SharedIncomeCreate(
        description=(form.get("description") or form.get("payee") or "").strip() or "Shared income",
        total_amount=total,
        category_id=_uuid(form.get("income_category_id", "")),
        theirs=theirs,
        received_by=got,
        deposits=[IncomeDepositIn(account_id=account, amount=landed)] if landed > 0 and account else [],
        **extra,
    )


@router.post("/income/preview")
async def income_preview(request: Request, contacts: Contacts, incomes: SharedIncomes):
    form = {k: str(v) for k, v in (await request.form()).items()}
    context: dict[str, Any] = {"preview": None, "message": None}
    if (form.get("total_amount") or form.get("total") or "").strip():
        try:
            context["preview"] = incomes.preview(income_data(form, contacts.cr.list()))
        except (ValueError, ValidationError) as e:
            context["message"] = _message(e)
    return templates.TemplateResponse(request, "partials/income_preview.html", context)


@router.post("/expense/preview")
async def expense_preview(request: Request, contacts: Contacts, expenses: SharedExpenses):
    form = {k: str(v) for k, v in (await request.form()).items()}
    context: dict[str, Any] = {"preview": None, "message": None}
    if (form.get("total_amount") or form.get("total") or "").strip():
        try:
            context["preview"] = expenses.preview(expense_data(form, contacts.cr.list()))
        except (ValueError, ValidationError) as e:
            context["message"] = _message(e)
    return templates.TemplateResponse(request, "partials/expense_preview.html", context)


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
    incomes: SharedIncomes,
):
    _person(contacts, contact_id)
    found = [i for i in summaries.activity(contact_id, limit=200).items if i.transaction_id == transaction_id]
    if not found:
        raise HTTPException(status_code=404, detail="entry not found")
    try:
        if found[0].purpose == "settlement":
            settlements.reverse(transaction_id)
        elif found[0].purpose == "income":
            incomes.cancel(transaction_id)
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
