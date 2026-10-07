from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...dependencies import Accounts, Recurring
from ...schemas.recurring import RecurringCreate, RecurringRead, RecurringUpdate
from ...services.schedule import describe
from ...templating import templates
from .accounts import build_tree, posting_groups
from .utils import htmx_error, htmx_redirect, parse_amount, validation_message


router = APIRouter(prefix="/recurring")

FREQUENCIES = [("daily", "day"), ("weekly", "week"), ("monthly", "month"), ("yearly", "year")]


@dataclass
class RuleRow:
    rule: RecurringRead
    from_name: str
    to_name: str
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
    return RuleRow(
        rule=rule,
        from_name=paths.get(rule.from_account, "?"),
        to_name=paths.get(rule.to_account, "?"),
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


def _form_context(accounts: Accounts, **extra) -> dict:
    all_accounts = accounts.list()
    return {
        "active": "transactions",
        "hide_fab": True,
        "groups": posting_groups(build_tree(all_accounts)),
        "frequencies": FREQUENCIES,
        "today": date.today().isoformat(),
        **extra,
    }


@router.get("/new")
def new_recurring_page(request: Request, accounts: Accounts):
    return templates.TemplateResponse(
        request,
        "recurring_form.html",
        _form_context(accounts, editing=False, rule=None),
    )


def _parse_date(value: str, label: str) -> date | None:
    if not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(f"{label} is not a valid date!")


def _parse(
    from_account: str, to_account: str, amount: str, to_amount: str, payee: str, comment: str,
    frequency: str, every: str, start: str, end: str,
) -> dict:
    if not from_account or not to_account:
        raise ValueError("choose both a from and a to account!")
    try:
        count = int(every.strip() or "1")
    except ValueError:
        raise ValueError("'every' must be a whole number!")
    started = _parse_date(start, "the start date")
    if started is None:
        raise ValueError("choose a start date!")
    received: Decimal | None = parse_amount(to_amount) if to_amount.strip() else None
    return {
        "from_account": UUID(from_account),
        "to_account": UUID(to_account),
        "amount": parse_amount(amount),
        "received_amount": received,
        "payee": payee,
        "comment": comment,
        "frequency": frequency,
        "every": count,
        "start_date": started,
        "end_date": _parse_date(end, "the end date"),
    }


@router.post("")
def create_recurring(
    recurring: Recurring,
    amount: Annotated[str, Form()] = "",
    to_amount: Annotated[str, Form()] = "",
    from_account: Annotated[str, Form()] = "",
    to_account: Annotated[str, Form()] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    frequency: Annotated[str, Form()] = "monthly",
    every: Annotated[str, Form()] = "1",
    start: Annotated[str, Form()] = "",
    end: Annotated[str, Form()] = "",
):
    try:
        data = RecurringCreate(
            **_parse(from_account, to_account, amount, to_amount, payee, comment, frequency, every, start, end)
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
        _form_context(accounts, editing=True, rule=rule, status=_status(rule), schedule=describe(rule.frequency, rule.every)),
    )


@router.post("/{rid}/edit")
def update_recurring(
    rid: UUID,
    recurring: Recurring,
    amount: Annotated[str, Form()] = "",
    to_amount: Annotated[str, Form()] = "",
    from_account: Annotated[str, Form()] = "",
    to_account: Annotated[str, Form()] = "",
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    frequency: Annotated[str, Form()] = "monthly",
    every: Annotated[str, Form()] = "1",
    start: Annotated[str, Form()] = "",
    end: Annotated[str, Form()] = "",
):
    try:
        data = RecurringUpdate(
            **_parse(from_account, to_account, amount, to_amount, payee, comment, frequency, every, start, end)
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
