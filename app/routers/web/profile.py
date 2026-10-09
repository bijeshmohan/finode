from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import ValidationError

from ...auth import CurrentUser, require_authenticated_user
from ...dependencies import ApiTokens, Data, OAuthGrants, Profiles
from ...schemas.api_token import ApiTokenCreate
from ...schemas.profile import ProfileUpdate
from ...templating import templates
from .utils import htmx_error, htmx_redirect, validation_message


router = APIRouter(prefix="/profile")


@router.get("")
def profile_page(
    request: Request,
    profiles: Profiles,
    user: Annotated[CurrentUser, Depends(require_authenticated_user)],
):
    profile = profiles.read()
    names = [n for n in (profile.first_name, profile.last_name) if n]
    initials = "".join(n[0] for n in names[:2]).upper() or (user.email or "?")[0].upper()
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "active": "profile",
            "profile": profile,
            "email": user.email,
            "display_name": " ".join(names),
            "initials": initials,
        },
    )


@router.get("/data")
def data_page(request: Request, data: Data):
    return templates.TemplateResponse(
        request, "profile_data.html", {"active": "profile", "can_import": data.can_import()}
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
    return htmx_redirect("/profile", flash="profile-updated")


def mcp_url(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/mcp"


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


@router.post("/assistants/{tkid}/access")
def change_token_access(tkid: UUID, tokens: ApiTokens, scope: Annotated[str, Form()] = ""):
    try:
        tokens.set_scope(tkid, scope)
    except LookupError:
        raise HTTPException(status_code=404, detail="token not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return htmx_redirect("/profile/assistants", flash="access-changed")


@router.post("/assistants/{tkid}/revoke")
def revoke_token(tkid: UUID, tokens: ApiTokens):
    try:
        tokens.revoke(tkid)
    except LookupError:
        raise HTTPException(status_code=404, detail="token not found")
    return htmx_redirect("/profile/assistants", flash="token-revoked")
