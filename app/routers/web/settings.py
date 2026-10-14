from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Form, Request
from pydantic import ValidationError

from ...clock import local_today
from ...config import settings
from ...dependencies import Accounts, Profiles
from ...schemas.profile import ProfileUpdate
from ...services.depth import ROOT_DEPTH_FIELDS
from ...templating import templates
from .utils import htmx_error, htmx_redirect, validation_message


router = APIRouter(prefix="/settings")


def _saved(row: str) -> str:
    """Back to the settings page with the row open. The query makes it a new address, so the page really reloads
    (a redirect that only adds a #fragment to the page you are on would leave the old values showing)."""
    return f"/settings?saved={row}#{row}"


@router.get("")
def settings_page(request: Request, profiles: Profiles, accounts: Accounts):
    profile = profiles.read()
    deepest = profiles.deepest()
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active": "settings",
            "profile": profile,
            "currencies": [c for c in accounts.commodity_choices() if c.kind == "currency"],
            "depths": [
                {
                    "root": root,
                    "field": field,
                    "value": getattr(profile, field),
                    "deepest": deepest[root],
                }
                for root, field in ROOT_DEPTH_FIELDS.items()
            ],
            "depth_cap": settings.max_account_depth,
            "yesterday": (local_today() - timedelta(days=1)).isoformat(),
        },
    )


@router.post("/currency")
def update_currency(profiles: Profiles, currency: Annotated[str, Form()] = ""):
    try:
        profiles.update(ProfileUpdate(default_currency=currency))
    except (ValidationError, ValueError) as e:
        message = validation_message(e) if isinstance(e, ValidationError) else str(e)
        return htmx_error(message, "#currency-error")
    return htmx_redirect(_saved("currency"), flash="currency-updated")


@router.post("/lock")
def update_lock(profiles: Profiles, locked_through: Annotated[str, Form()] = ""):
    """Lock the books up to a day; an empty day removes the lock."""
    try:
        day = date.fromisoformat(locked_through.strip()) if locked_through.strip() else None
    except ValueError:
        return htmx_error("choose a date!", "#lock-error")
    try:
        profiles.update(ProfileUpdate(locked_through=day))
    except (ValidationError, ValueError) as e:
        message = validation_message(e) if isinstance(e, ValidationError) else str(e)
        return htmx_error(message, "#lock-error")
    return htmx_redirect(_saved("lock"), flash="lock-saved" if day else "lock-removed")


@router.post("/depth")
def update_depth(
    profiles: Profiles,
    max_depth_assets: Annotated[str, Form()] = "",
    max_depth_liabilities: Annotated[str, Form()] = "",
    max_depth_equity: Annotated[str, Form()] = "",
    max_depth_income: Annotated[str, Form()] = "",
    max_depth_expenses: Annotated[str, Form()] = "",
):
    submitted = {
        "max_depth_assets": max_depth_assets,
        "max_depth_liabilities": max_depth_liabilities,
        "max_depth_equity": max_depth_equity,
        "max_depth_income": max_depth_income,
        "max_depth_expenses": max_depth_expenses,
    }
    values = {}
    for root, field in ROOT_DEPTH_FIELDS.items():
        text = submitted[field].strip()
        if not text:
            continue
        try:
            number = int(text)
        except ValueError:
            return htmx_error(f"{root}: '{text}' is not a whole number!", "#depth-error")
        if number < 0:
            return htmx_error(f"{root}: depth cannot be negative!", "#depth-error")
        values[field] = number
    try:
        profiles.update(ProfileUpdate(**values))
    except (ValidationError, ValueError) as e:
        message = validation_message(e) if isinstance(e, ValidationError) else str(e)
        return htmx_error(message, "#depth-error")
    return htmx_redirect(_saved("depth"), flash="depth-updated")
