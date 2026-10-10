from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...dependencies import Accounts, Recurring
from ...models.transaction import PostingSide
from ...schemas.recurring import RecurringCreate, RecurringPostingData, RecurringRead, RecurringUpdate
from ...services.schedule import describe
from ...templating import templates
from .accounts import build_tree
from .transactions import form_context, form_rows, split_postings
from .utils import htmx_error, htmx_redirect, parse_amount, validation_message


router = APIRouter(prefix="/recurring")

FREQUENCIES = [("daily", "day"), ("weekly", "week"), ("monthly", "month"), ("yearly", "year")]


@dataclass
class RuleRow:
    rule: RecurringRead
    from_name: str
    to_name: str
    amount: Decimal  # what leaves (a split: its total, in the rule's currency)
    unit: str | None  # commodity of the 'from' account, shown when it is not the default currency
    schedule: str
    status: str  # active | paused | ended | error


def _status(rule: RecurringRead) -> str:
    if rule.active:
        return "error" if rule.last_error else "active"
    return "ended" if rule.end_date is not None and rule.next_date > rule.end_date else "paused"


def _paths(accounts: Accounts) -> tuple[dict[UUID, str], dict[UUID, str | None]]:
    all_accounts = accounts.list()
    paths = {n.account.aid: n.path for root in build_tree(all_accounts) for n in root.walk()}
    return paths, {a.aid: a.commodity for a in all_accounts}


def _row(rule: RecurringRead, paths: dict[UUID, str], commodities: dict[UUID, str | None]) -> RuleRow:
    if rule.postings:
        names = lambda side: ", ".join(  # noqa: E731
            dict.fromkeys(paths.get(p.account, "?").split(" › ")[-1] for p in rule.postings if p.side == side)
        )
        total = sum((p.value or p.amount for p in rule.postings if p.side == PostingSide.DEBIT), Decimal(0))
        return RuleRow(
            rule=rule, from_name=names(PostingSide.CREDIT), to_name=names(PostingSide.DEBIT), amount=total,
            unit=rule.currency, schedule=describe(rule.frequency, rule.every), status=_status(rule),
        )
    return RuleRow(
        rule=rule,
        from_name=paths.get(rule.from_account, "?"),
        to_name=paths.get(rule.to_account, "?"),
        amount=rule.amount,
        unit=commodities.get(rule.from_account),
        schedule=describe(rule.frequency, rule.every),
        status=_status(rule),
    )


@router.get("")
def recurring_page(request: Request, accounts: Accounts, recurring: Recurring):
    recurring.process_due()
    paths, commodities = _paths(accounts)
    rows = [_row(r, paths, commodities) for r in recurring.list()]
    return templates.TemplateResponse(
        request,
        "recurring.html",
        {
            "active": "transactions",
            "hide_fab": True,
            "rows": rows,
            "live": [r for r in rows if r.status in ("active", "error")],
            "stopped": [r for r in rows if r.status in ("paused", "ended")],
            "currency": accounts.default_currency().code,
        },
    )


def _form_page(accounts: Accounts, recurring: Recurring, rule: RecurringRead | None, **extra) -> dict:
    """The shared transaction rows (total, From and To) filled from the rule: simple and split alike."""
    if rule is None:
        transaction, total, from_rows, to_rows = None, "", form_rows([], PostingSide.CREDIT), form_rows([], PostingSide.DEBIT)
    else:
        recorded = recurring.as_transaction(rule)
        transaction = SimpleNamespace(currency=recorded.currency)
        total = sum((p.value or p.amount for p in recorded.postings if p.side == PostingSide.DEBIT), Decimal(0))
        from_rows = form_rows(recorded.postings, PostingSide.CREDIT)
        to_rows = form_rows(recorded.postings, PostingSide.DEBIT)
    return form_context(
        accounts,
        editing=rule is not None,
        rule=rule,
        transaction=transaction,
        total=total,
        from_rows=from_rows,
        to_rows=to_rows,
        frequencies=FREQUENCIES,
        today=date.today().isoformat(),
        **extra,
    )


@router.get("/new")
def new_recurring_page(request: Request, accounts: Accounts, recurring: Recurring):
    return templates.TemplateResponse(request, "recurring_form.html", _form_page(accounts, recurring, None))


def _parse_date(value: str, label: str) -> date | None:
    if not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"{label} is not a valid date!")


def _parse(
    accounts: Accounts, account: list[str], side: list[str], amount: list[str], value: list[str], currency: str,
    payee: str, comment: str, frequency: str, every: str, start: str, end: str,
) -> dict:
    try:
        count = int(every.strip() or "1")
    except ValueError:
        raise ValueError("'every' must be a whole number!")
    started = _parse_date(start, "the start date")
    if started is None:
        raise ValueError("choose a start date!")
    rows = split_postings(account, side, amount, value)
    if len(rows) < 2:
        raise ValueError("choose where the money comes from and where it goes!")
    common = {
        "payee": payee, "comment": comment, "frequency": frequency, "every": count,
        "start_date": started, "end_date": _parse_date(end, "the end date"),
    }
    debit = [p for p in rows if p.side == PostingSide.DEBIT]
    credit = [p for p in rows if p.side == PostingSide.CREDIT]
    if len(rows) == 2 and len(debit) == 1 and len(credit) == 1:
        # One account on each side is a plain rule (finode works out the currency and what is worth what).
        held = {a.aid: a.commodity for a in accounts.list()}
        converts = held.get(debit[0].account) != held.get(credit[0].account)
        if converts or debit[0].amount == credit[0].amount:
            return {
                "from_account": credit[0].account, "to_account": debit[0].account, "amount": credit[0].amount,
                "received_amount": debit[0].amount if converts else None, **common,
            }
    return {
        "postings": [
            RecurringPostingData(account=p.account, side=p.side, amount=p.amount, value=p.value) for p in rows
        ],
        "currency": currency.strip() or None,
        **common,
    }


@router.post("")
def create_recurring(
    accounts: Accounts,
    recurring: Recurring,
    account: Annotated[list[str], Form()] = [],
    side: Annotated[list[str], Form()] = [],
    amount: Annotated[list[str], Form()] = [],
    value: Annotated[list[str], Form()] = [],
    currency: Annotated[str, Form()] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    frequency: Annotated[str, Form()] = "monthly",
    every: Annotated[str, Form()] = "1",
    start: Annotated[str, Form()] = "",
    end: Annotated[str, Form()] = "",
):
    try:
        data = RecurringCreate(
            **_parse(accounts, account, side, amount, value, currency, payee, comment, frequency, every, start, end)
        )
        created = recurring.create(data)
        recurring.process_due()  # a start date in the past is recorded straight away
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect("/recurring", flash="recurring-saved")


@router.get("/{rid}/edit")
def edit_recurring_page(request: Request, rid: UUID, accounts: Accounts, recurring: Recurring):
    rule = recurring.read(rid)
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return templates.TemplateResponse(
        request,
        "recurring_form.html",
        _form_page(accounts, recurring, rule, status=_status(rule), schedule=describe(rule.frequency, rule.every)),
    )


@router.post("/{rid}/edit")
def update_recurring(
    rid: UUID,
    accounts: Accounts,
    recurring: Recurring,
    account: Annotated[list[str], Form()] = [],
    side: Annotated[list[str], Form()] = [],
    amount: Annotated[list[str], Form()] = [],
    value: Annotated[list[str], Form()] = [],
    currency: Annotated[str, Form()] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    frequency: Annotated[str, Form()] = "monthly",
    every: Annotated[str, Form()] = "1",
    start: Annotated[str, Form()] = "",
    end: Annotated[str, Form()] = "",
):
    try:
        data = RecurringUpdate(
            **_parse(accounts, account, side, amount, value, currency, payee, comment, frequency, every, start, end)
        )
        rule = recurring.update(rid, data)
        if rule is not None:
            recurring.process_due()
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-saved")


@router.post("/{rid}/pause")
def pause_recurring(rid: UUID, recurring: Recurring):
    if recurring.set_active(rid, False) is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-paused")


@router.post("/{rid}/resume")
def resume_recurring(rid: UUID, recurring: Recurring):
    try:
        rule = recurring.set_active(rid, True)
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-resumed")


@router.post("/{rid}/delete")
def delete_recurring(rid: UUID, recurring: Recurring):
    if not recurring.delete(rid):
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-deleted")
