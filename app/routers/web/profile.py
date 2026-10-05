from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from pydantic import ValidationError

from ...auth import CurrentUser, require_authenticated_user
from ...dependencies import Data, Profiles
from ...schemas.profile import ProfileUpdate
from ...templating import templates
from .utils import htmx_error, htmx_redirect, validation_message


router = APIRouter(prefix="/profile")


@router.get("")
def profile_page(
    request: Request,
    profiles: Profiles,
    data: Data,
    user: Annotated[CurrentUser, Depends(require_authenticated_user)],
):
    return templates.TemplateResponse(
        request,
        "profile.html",
        {"active": "profile", "profile": profiles.read(), "email": user.email, "can_import": data.can_import()},
    )


@router.post("")
def update_profile(
    profiles: Profiles,
    first_name: Annotated[str, Form()] = "",
    last_name: Annotated[str, Form()] = "",
):
    try:
        profiles.update(ProfileUpdate(first_name=first_name, last_name=last_name))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#form-error")
    return htmx_redirect("/app/profile", flash="profile-updated")
