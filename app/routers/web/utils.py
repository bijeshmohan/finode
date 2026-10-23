import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import UUID
from html import escape

from fastapi import Response
from fastapi.responses import HTMLResponse

from ...flash import set_flash


from ...services.validation import validation_message  # noqa: F401  (shared with the services)


@dataclass
class UpcomingItem:
    """One entry dated ahead, as the "upcoming" card shows it (see partials/upcoming.html)."""

    tid: UUID
    date: date
    title: str
    sub: str
    amount: Decimal
    income: bool = False


def parse_amount(value: str | None, default: Decimal | None = None) -> Decimal:
    value = (value or "").strip().replace(",", "")
    if not value:
        if default is None:
            raise ValueError("amount is required!")
        return default
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"'{value}' is not a valid amount!")
    if not amount.is_finite():
        raise ValueError(f"'{value}' is not a valid amount!")
    return amount


def htmx_redirect(location: str, flash: str | None = None, undo: tuple[str, UUID] | None = None) -> Response:
    response = Response(status_code=200, headers={"HX-Redirect": location})
    if flash:
        set_flash(response, flash, undo)
    return response


def htmx_trigger(event: str, detail: dict) -> Response:
    """Fire a browser event on the page; json.dumps escapes non-ASCII, so the header stays valid."""
    return Response(status_code=200, headers={"HX-Trigger": json.dumps({event: detail})})


def htmx_error(message: str, target: str, status_code: int = 400) -> HTMLResponse:
    return HTMLResponse(
        escape(message),
        status_code=status_code,
        headers={"HX-Retarget": target, "HX-Reswap": "innerHTML"},
    )
