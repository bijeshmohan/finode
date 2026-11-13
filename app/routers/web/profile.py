"""The Your data page (erase, delete my account), the profile form and the Assistants page with its tokens."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import ValidationError

from ...auth import CurrentUser, require_authenticated_user
from ...config import settings
from ...dependencies import ApiTokens, Backup, Data, Erase, OAuthGrants, Profiles
from ...schemas.api_token import ApiTokenCreate
from ...schemas.profile import ProfileUpdate
from ...session import AuthUnavailableError, clear_auth_cookies
from ...signup import delete_user
from ...templating import templates
from ..assistants import mcp_url
from ..data import confirmed
from .utils import htmx_error, htmx_redirect, validation_message

router = APIRouter(prefix="/profile")


@router.get("/data")
def data_page(
    request: Request,
    data: Data,
    backup: Backup,
    user: Annotated[CurrentUser, Depends(require_authenticated_user)],
):
    return templates.TemplateResponse(
        request,
        "profile_data.html",
        {
            "active": "profile",
            "can_import": data.can_import(),
            "can_restore": backup.can_restore(),
            "confirm_word": user.email or "DELETE",
            "can_delete_login": settings.can_delete_logins,
        },
    )


@router.post("/data/erase")
def erase_books(
    user: Annotated[CurrentUser, Depends(require_authenticated_user)],
    erase: Erase,
    confirm: Annotated[str, Form()] = "",
):
    if not confirmed(user, confirm):
        return htmx_error(f"Type {user.email or 'DELETE'} to confirm.", "#erase-error")
    erase.erase_books()
    return htmx_redirect("/", flash="books-erased")


@router.post("/data/delete-account")
def delete_account(
    user: Annotated[CurrentUser, Depends(require_authenticated_user)],
    erase: Erase,
    confirm: Annotated[str, Form()] = "",
):
    if not confirmed(user, confirm):
        return htmx_error(f"Type {user.email or 'DELETE'} to confirm.", "#delete-error")
    if not settings.can_delete_logins:
        return htmx_error("Deleting your login is not set up here: ask the person who runs finode.", "#delete-error")
    erase.erase_everything()
    try:
        delete_user(user.id)
    except AuthUnavailableError:
        # The books are gone; the sign-in is not. Say so, and let them (or the admin) finish it.
        return htmx_error(
            "Your data was erased, but removing your login failed. Try again, or ask the person who runs finode.",
            "#delete-error",
        )
    response = htmx_redirect("/login", flash="your-account-deleted")
    clear_auth_cookies(response)
    return response


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
    return htmx_redirect("/settings", flash="profile-updated")


@router.get("/assistants")
def assistants_page(request: Request, tokens: ApiTokens, grants: OAuthGrants):
    return templates.TemplateResponse(
        request,
        "assistants.html",
        {
            "active": "profile",
            "tokens": [t for t in tokens.list() if t.revoked is None],
            "apps": grants.list(),
            "mcp_url": mcp_url(request),
            "created": None,
        },
    )


@router.post("/assistants")
def create_token(
    request: Request,
    tokens: ApiTokens,
    grants: OAuthGrants,
    name: Annotated[str, Form()] = "",
    scope: Annotated[str, Form()] = "read",
):
    try:
        created = tokens.create(ApiTokenCreate(name=name, scope=scope))
    except ValidationError as e:
        return htmx_error(validation_message(e), "#token-error")
    except ValueError as e:
        return htmx_error(str(e), "#token-error")
    # The secret is shown this once, with the setup snippets filled in; the list refreshes alongside.
    return templates.TemplateResponse(
        request,
        "partials/token_created.html",
        {
            "created": created,
            "tokens": [t for t in tokens.list() if t.revoked is None],
            "apps": grants.list(),
            "mcp_url": mcp_url(request),
        },
    )


@router.post("/assistants/{token_id}/access")
def change_token_access(token_id: UUID, tokens: ApiTokens, scope: Annotated[str, Form()] = ""):
    try:
        tokens.set_scope(token_id, scope)
    except LookupError:
        raise HTTPException(status_code=404, detail="token not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return htmx_redirect("/profile/assistants", flash="access-changed")


@router.post("/assistants/{token_id}/revoke")
def revoke_token(token_id: UUID, tokens: ApiTokens):
    try:
        tokens.revoke(token_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="token not found") from None
    return htmx_redirect("/profile/assistants", flash="token-revoked")
