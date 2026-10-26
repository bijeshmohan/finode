from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import Accounts, Recurring
from ...models.transaction import PostingSide
from ...schemas.recurring import RecurringCreate, RecurringPostingData, RecurringRead, RecurringUpdate
from ...services.schedule import describe
from ...templating import templates
from .accounts import build_tree
from .transactions import form_context, form_rows, infer_kind, split_postings
from .utils import htmx_error, htmx_redirect, validation_message

router = APIRouter(prefix="/recurring")

FREQUENCIES = [("daily", "day"), ("weekly", "week"), ("monthly", "month"), ("yearly", "year")]


@dataclass
class RuleRow:
    rule: RecurringRead
    from_name: str
    to_name: str
    amount: Decimal  # what leaves (a split: its total)
    schedule: str
    status: str  # active | paused | ended | error


def _status(rule: RecurringRead) -> str:
    if rule.active:
        return "error" if rule.last_error else "active"
    return "ended" if rule.end_date is not None and rule.next_date > rule.end_date else "paused"


def _paths(accounts: Accounts) -> dict[UUID, str]:
    return {n.account.aid: n.path for root in build_tree(accounts.list()) for n in root.walk()}


def _row(rule: RecurringRead, paths: dict[UUID, str]) -> RuleRow:
    if rule.postings:
        names = lambda side: ", ".join(  # noqa: E731
            dict.fromkeys(paths.get(p.account, "?").split(" › ")[-1] for p in rule.postings if p.side == side)
        )
        total = sum((p.amount for p in rule.postings if p.side == PostingSide.DEBIT), Decimal(0))
        return RuleRow(
            rule=rule,
            from_name=names(PostingSide.CREDIT),
            to_name=names(PostingSide.DEBIT),
            amount=total,
            schedule=describe(rule.frequency, rule.every),
            status=_status(rule),
        )
    return RuleRow(
        rule=rule,
        from_name=paths.get(rule.from_account, "?") if rule.from_account else "?",
        to_name=paths.get(rule.to_account, "?") if rule.to_account else "?",
        amount=rule.amount or Decimal(0),
        schedule=describe(rule.frequency, rule.every),
        status=_status(rule),
    )


@router.get("")
def recurring_page(request: Request, accounts: Accounts, recurring: Recurring):
    recurring.process_due()
    paths = _paths(accounts)
    rows = [_row(r, paths) for r in recurring.list()]
    return templates.TemplateResponse(
        request,
        "recurring.html",
        {
            "active": "transactions",
            "hide_fab": True,
            "rows": rows,
            "live": [r for r in rows if r.status in ("active", "error")],
            "stopped": [r for r in rows if r.status in ("paused", "ended")],
            "currency": accounts.currency().code,
        },
    )


def _form_page(accounts: Accounts, recurring: Recurring, rule: RecurringRead | None, **extra) -> dict:
    """The shared transaction rows (total, From and To) filled from the rule: simple and split alike."""
    total: Decimal | str
    keep: set[UUID] | tuple[()]
    if rule is None:
        transaction, total, from_rows, to_rows = (
            None,
            "",
            form_rows([], PostingSide.CREDIT),
            form_rows([], PostingSide.DEBIT),
        )
        kind = "expense"
        keep = ()
    else:
        recorded = recurring.as_transaction(rule)
        keep = {p.account for p in recorded.postings}
        transaction = None
        total = sum((p.amount for p in recorded.postings if p.side == PostingSide.DEBIT), Decimal(0))
        kind = infer_kind(
            recorded.postings, {n.account.aid: r.account.name for r in build_tree(accounts.list()) for n in r.walk()}
        )
        from_rows = form_rows(recorded.postings, PostingSide.CREDIT)
        to_rows = form_rows(recorded.postings, PostingSide.DEBIT)
    return form_context(
        accounts,
        editing=rule is not None,
        kind=kind,
        rule=rule,
        transaction=transaction,
        total=total,
        from_rows=from_rows,
        to_rows=to_rows,
        keep=keep,
        frequencies=FREQUENCIES,
        today=local_today().isoformat(),
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
        raise ValueError(f"{label} is not a valid date!") from None


def _parse(
    account: list[str],
    side: list[str],
    amount: list[str],
    payee: str,
    comment: str,
    frequency: str,
    every: str,
    start: str,
    end: str,
    tags: list[str],
) -> dict:
    try:
        count = int(every.strip() or "1")
    except ValueError:
        raise ValueError("'every' must be a whole number!") from None
    started = _parse_date(start, "the start date")
    if started is None:
        raise ValueError("choose a start date!")
    rows = split_postings(account, side, amount)
    if len(rows) < 2:
        raise ValueError("choose where the money comes from and where it goes!")
    common = {
        "payee": payee,
        "comment": comment,
        "tags": tags,
        "frequency": frequency,
        "every": count,
        "start_date": started,
        "end_date": _parse_date(end, "the end date"),
    }
    debit = [p for p in rows if p.side == PostingSide.DEBIT]
    credit = [p for p in rows if p.side == PostingSide.CREDIT]
    if len(rows) == 2 and len(debit) == 1 and len(credit) == 1 and debit[0].amount == credit[0].amount:
        # One account on each side is a plain rule.
        return {
            "from_account": credit[0].account,
            "to_account": debit[0].account,
            "amount": credit[0].amount,
            **common,
        }
    return {
        "postings": [RecurringPostingData(account=p.account, side=p.side, amount=p.amount) for p in rows],
        **common,
    }


@router.post("")
def create_recurring(
    accounts: Accounts,
    recurring: Recurring,
    account: Annotated[list[str] | None, Form()] = None,
    side: Annotated[list[str] | None, Form()] = None,
    amount: Annotated[list[str] | None, Form()] = None,
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    frequency: Annotated[str, Form()] = "monthly",
    every: Annotated[str, Form()] = "1",
    start: Annotated[str, Form()] = "",
    end: Annotated[str, Form()] = "",
    tags: Annotated[list[str] | None, Form()] = None,
):
    account, side, amount, tags = account or [], side or [], amount or [], tags or []
    try:
        data = RecurringCreate(**_parse(account, side, amount, payee, comment, frequency, every, start, end, tags))
        recurring.create(data)
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
    account: Annotated[list[str] | None, Form()] = None,
    side: Annotated[list[str] | None, Form()] = None,
    amount: Annotated[list[str] | None, Form()] = None,
    payee: Annotated[str, Form()] = "",
    comment: Annotated[str, Form()] = "",
    frequency: Annotated[str, Form()] = "monthly",
    every: Annotated[str, Form()] = "1",
    start: Annotated[str, Form()] = "",
    end: Annotated[str, Form()] = "",
    tags: Annotated[list[str] | None, Form()] = None,
):
    account, side, amount, tags = account or [], side or [], amount or [], tags or []
    try:
        data = RecurringUpdate(**_parse(account, side, amount, payee, comment, frequency, every, start, end, tags))
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


@router.post("/{rid}/skip")
def skip_recurring(rid: UUID, recurring: Recurring):
    try:
        rule = recurring.skip_next(rid)
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-skipped")


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
