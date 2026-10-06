"""The consent step of "Sign in with finode" for AI assistants: Supabase sends the user here."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ... import oauth
from ...dependencies import OAuthGrants
from ...templating import templates
from .utils import htmx_redirect


router = APIRouter(prefix="/oauth")


def _problem(request: Request, message: str, status_code: int = 400):
    return templates.TemplateResponse(
        request, "oauth_consent.html", {"active": "profile", "hide_fab": True, "problem": message, "details": None},
        status_code=status_code,
    )


@router.get("/consent")
def consent_page(request: Request, authorization_id: str = ""):
    if not authorization_id.strip():
        return _problem(request, "This page is opened by an app that wants to connect. Start from the app's connector settings.")
    try:
        details = oauth.authorization_details(authorization_id.strip(), request.state.access_token)
    except oauth.OAuthError as e:
        return _problem(request, str(e))
    if details.redirect_url:
        # Already decided earlier: Supabase only wants the user sent back.
        return RedirectResponse(details.redirect_url, status_code=303) if oauth.is_web_url(details.redirect_url) else _problem(
            request, "The app asked to be opened in a way finode does not allow."
        )
    return templates.TemplateResponse(
        request,
        "oauth_consent.html",
        {"active": "profile", "hide_fab": True, "problem": None, "details": details},
    )


@router.post("/consent")
def decide(
    request: Request,
    grants: OAuthGrants,
    authorization_id: Annotated[str, Form()] = "",
    action: Annotated[str, Form()] = "deny",
    access: Annotated[str, Form()] = "read",
):
    token = request.state.access_token
    approve = action == "allow"
    try:
        if approve:
            # The app is whatever Supabase says it is for this request, not what the form claims.
            details = oauth.authorization_details(authorization_id, token)
            grants.allow(details.client_id, details.client_name, access)
        redirect = oauth.decide(authorization_id, approve, token)
    except (oauth.OAuthError, ValueError) as e:
        return _problem(request, str(e))
    if not oauth.is_web_url(redirect):
        return _problem(request, "The app asked to be opened in a way finode does not allow.")
    return RedirectResponse(redirect, status_code=303)


@router.post("/apps/{gid}/disconnect")
def disconnect(request: Request, gid: UUID, grants: OAuthGrants):
    try:
        grant = grants.revoke(gid)
    except LookupError:
        raise HTTPException(status_code=404, detail="app not found")
    oauth.revoke_grant(grant.client_id, request.state.access_token)
    return htmx_redirect("/app/profile/assistants", flash="app-disconnected")
