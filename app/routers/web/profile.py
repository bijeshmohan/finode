from typing import Annotated

from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import ValidationError

from ...config import settings
from ...auth import CurrentUser, require_authenticated_user
from ...dependencies import Accounts, ApiTokens, Data, OAuthGrants, Profiles
from ...schemas.api_token import ApiTokenCreate
from ...schemas.profile import ProfileUpdate
from ...services.depth import ROOT_DEPTH_FIELDS
from ...templating import templates
from .utils import htmx_error, htmx_redirect, validation_message


router = APIRouter(prefix="/profile")


@router.get("")
def profile_page(
    request: Request,
    profiles: Profiles,
    accounts: Accounts,
    user: Annotated[CurrentUser, Depends(require_authenticated_user)],
):
    profile = profiles.read()
    names = [n for n in (profile.first_name, profile.last_name) if n]
    initials = "".join(n[0] for n in names[:2]).upper() or (user.email or "?")[0].upper()
    deepest = profiles.deepest()
    return templates.TemplateResponse(
        request,
        "profile.html",
        {
            "active": "profile",
            "profile": profile,
            "email": user.email,
            "display_name": " ".join(names),
            "initials": initials,
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
    return htmx_redirect("/app/profile", flash="profile-updated")


@router.post("/currency")
def update_currency(profiles: Profiles, currency: Annotated[str, Form()] = ""):
    try:
        profiles.update(ProfileUpdate(default_currency=currency))
    except (ValidationError, ValueError) as e:
        message = validation_message(e) if isinstance(e, ValidationError) else str(e)
        return htmx_error(message, "#currency-error")
    return htmx_redirect("/app/profile#currency", flash="currency-updated")


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
    return htmx_redirect("/app/profile#depth", flash="depth-updated")


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
    return htmx_redirect("/app/profile/assistants", flash="access-changed")


@router.post("/assistants/{tkid}/revoke")
def revoke_token(tkid: UUID, tokens: ApiTokens):
    try:
        tokens.revoke(tkid)
    except LookupError:
        raise HTTPException(status_code=404, detail="token not found")
    return htmx_redirect("/app/profile/assistants", flash="token-revoked")
