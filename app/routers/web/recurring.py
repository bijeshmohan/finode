"""The Recurring page and the form that makes, changes, pauses, skips, resumes and deletes a rule."""

from collections.abc import Mapping
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from pydantic import ValidationError

from ...clock import local_today
from ...dependencies import Accounts, Categories, Recurring
from ...schemas.recurring import RecurringCreate, RecurringRead, RecurringUpdate
from ...services.recurring_form import FREQUENCIES, form_start, rule_fields
from ...services.recurring_view import rule_rows, status
from ...services.schedule import describe
from ...templating import templates
from .transactions import category_places, form_context, form_entry_rows
from .utils import htmx_error, htmx_redirect, validation_message

router = APIRouter(prefix="/recurring")


@router.get("")
def recurring_page(request: Request, accounts: Accounts, categories: Categories, recurring: Recurring):
    found = rule_rows(recurring, accounts, categories)
    return templates.TemplateResponse(
        request,
        "recurring.html",
        {
            "active": "settings",
            "hide_fab": True,
            "rows": found.rows,
            "live": found.live,
            "stopped": found.stopped,
            "currency": accounts.currency().code,
        },
    )


def _form_page(
    accounts: Accounts, categories: Categories, recurring: Recurring, rule: RecurringRead | None, **extra
) -> dict:
    """The shared transaction rows (total, From and To) filled from the rule: simple and split alike."""
    start = form_start(recurring, accounts, rule)
    return form_context(
        accounts,
        categories,
        editing=rule is not None,
        kind=start.kind,
        rule=rule,
        transaction=None,
        total=start.total,
        from_rows=start.from_rows,
        to_rows=start.to_rows,
        keep=start.keep,
        frequencies=FREQUENCIES,
        today=local_today().isoformat(),
        **extra,
    )


@router.get("/new")
def new_recurring_page(request: Request, accounts: Accounts, categories: Categories, recurring: Recurring):
    return templates.TemplateResponse(request, "recurring_form.html", _form_page(accounts, categories, recurring, None))


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
    category: list[str] | None = None,
    places: Mapping[UUID, UUID] | None = None,
) -> dict:
    try:
        count = int(every.strip() or "1")
    except ValueError:
        raise ValueError("'every' must be a whole number!") from None
    started = _parse_date(start, "the start date")
    if started is None:
        raise ValueError("choose a start date!")
    return rule_fields(
        form_entry_rows(account, side, amount, category),
        places or {},
        payee=payee,
        comment=comment,
        tags=tags,
        frequency=frequency,
        every=count,
        start_date=started,
        end_date=_parse_date(end, "the end date"),
    )


@router.post("")
def create_recurring(
    accounts: Accounts,
    categories: Categories,
    recurring: Recurring,
    account: Annotated[list[str] | None, Form()] = None,
    side: Annotated[list[str] | None, Form()] = None,
    amount: Annotated[list[str] | None, Form()] = None,
    category: Annotated[list[str] | None, Form()] = None,
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
        data = RecurringCreate(
            **_parse(
                account,
                side,
                amount,
                payee,
                comment,
                frequency,
                every,
                start,
                end,
                tags,
                category,
                category_places(accounts, categories),
            )
        )
        recurring.create(data)
        recurring.process_due()  # a start date in the past is recorded straight away
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    return htmx_redirect("/recurring", flash="recurring-saved")


@router.get("/{recurring_id}/edit")
def edit_recurring_page(
    request: Request, recurring_id: UUID, accounts: Accounts, categories: Categories, recurring: Recurring
):
    rule = recurring.read(recurring_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return templates.TemplateResponse(
        request,
        "recurring_form.html",
        _form_page(
            accounts, categories, recurring, rule, status=status(rule), schedule=describe(rule.frequency, rule.every)
        ),
    )


@router.post("/{recurring_id}/edit")
def update_recurring(
    recurring_id: UUID,
    accounts: Accounts,
    categories: Categories,
    recurring: Recurring,
    account: Annotated[list[str] | None, Form()] = None,
    side: Annotated[list[str] | None, Form()] = None,
    amount: Annotated[list[str] | None, Form()] = None,
    category: Annotated[list[str] | None, Form()] = None,
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
        data = RecurringUpdate(
            **_parse(
                account,
                side,
                amount,
                payee,
                comment,
                frequency,
                every,
                start,
                end,
                tags,
                category,
                category_places(accounts, categories),
            )
        )
        rule = recurring.update(recurring_id, data)
        if rule is not None:
            recurring.process_due()
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-saved")


@router.post("/{recurring_id}/pause")
def pause_recurring(recurring_id: UUID, recurring: Recurring):
    if recurring.set_active(recurring_id, False) is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-paused")


@router.post("/{recurring_id}/skip")
def skip_recurring(recurring_id: UUID, recurring: Recurring):
    try:
        rule = recurring.skip_next(recurring_id)
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-skipped")


@router.post("/{recurring_id}/resume")
def resume_recurring(recurring_id: UUID, recurring: Recurring):
    try:
        rule = recurring.set_active(recurring_id, True)
    except ValueError as e:
        return htmx_error(str(e), "#form-error")
    if rule is None:
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-resumed")


@router.post("/{recurring_id}/delete")
def delete_recurring(recurring_id: UUID, recurring: Recurring):
    if not recurring.delete(recurring_id):
        raise HTTPException(status_code=404, detail="recurring transaction not found")
    return htmx_redirect("/recurring", flash="recurring-deleted")
