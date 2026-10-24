from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from pydantic import ValidationError

from ...auth import CurrentUser, require_authenticated_user
from ...config import settings
from ...currencies import CURRENCIES
from ...dependencies import Profiles
from ...schemas.profile import ProfileUpdate
from ...templating import templates
from .profile import _feedback_url
from .utils import htmx_error, htmx_redirect, validation_message

router = APIRouter(prefix="/settings")


def _saved(row: str, page: str = "/settings") -> str:
    """Back to a settings page with the row open. The query makes it a new address, so the page really reloads
    (a redirect that only adds a #fragment to the page you are on would leave the old values showing)."""
    return f"{page}?saved={row}#{row}"


@router.get("")
def settings_page(
    request: Request,
    profiles: Profiles,
    user: Annotated[CurrentUser, Depends(require_authenticated_user)],
):
    profile = profiles.read()
    names = [n for n in (profile.first_name, profile.last_name) if n]
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "active": "settings",
            "profile": profile,
            "currencies": list(CURRENCIES.values()),
            "email": user.email,
            "display_name": " ".join(names),
            "test_notice": settings.test_notice,
            "feedback_url": _feedback_url(),
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
