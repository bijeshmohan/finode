from decimal import Decimal, InvalidOperation
from html import escape

from fastapi import Response
from fastapi.responses import HTMLResponse
from pydantic import ValidationError


def validation_message(error: ValidationError) -> str:
    messages = []
    for item in error.errors():
        message = item["msg"].removeprefix("Value error, ")
        field = ".".join(str(part) for part in item["loc"] if not isinstance(part, int))
        messages.append(message if item["type"] == "value_error" or not field else f"{field}: {message}")
    return "; ".join(messages)


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


def htmx_redirect(location: str) -> Response:
    return Response(status_code=200, headers={"HX-Redirect": location})


def htmx_error(message: str, target: str, status_code: int = 400) -> HTMLResponse:
    return HTMLResponse(
        escape(message),
        status_code=status_code,
        headers={"HX-Retarget": target, "HX-Reswap": "innerHTML"},
    )
