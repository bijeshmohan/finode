"""JSON API for AI assistants (`/api/assistants`, `/api/oauth/consent`): personal access tokens, connected apps and the
consent screen an app sends you to.

Only for someone signed in to the finode app itself (`require_cookie_session`): a token, even a full sign-in token,
must never be able to mint tokens or let an app in.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import oauth
from ..auth import CookieSession, require_cookie_session
from ..dependencies import ApiTokens, OAuthGrants
from ..schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenRead
from ..schemas.assistants import (
    AccessChange,
    AssistantsRead,
    ConnectedAppRead,
    ConsentDecision,
    ConsentRead,
    ConsentResult,
)

router = APIRouter(prefix="/assistants", tags=["assistants"], dependencies=[Depends(require_cookie_session)])
consent_router = APIRouter(prefix="/oauth", tags=["assistants"])

NOT_A_WEB_ADDRESS = "The app asked to be opened in a way finode does not allow."


def mcp_url(request: Request) -> str:
    """The address assistants connect to."""
    return str(request.base_url).rstrip("/") + "/mcp"


@router.get("/", response_model=AssistantsRead)
def assistants(request: Request, tokens: ApiTokens, grants: OAuthGrants):
    """The MCP address, your tokens and the apps you connected (revoked ones left out)."""
    return AssistantsRead(
        mcp_url=mcp_url(request),
        tokens=[t for t in tokens.list() if t.revoked is None],
        apps=[ConnectedAppRead.model_validate(g, from_attributes=True) for g in grants.list()],
    )


@router.post("/tokens", status_code=201, response_model=ApiTokenCreated)
def create_token(data: ApiTokenCreate, tokens: ApiTokens):
    """A new token; its secret is in this answer only (just a hash is kept)."""
    try:
        return tokens.create(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/tokens/{token_id}/access", response_model=ApiTokenRead)
def change_token_access(token_id: UUID, data: AccessChange, tokens: ApiTokens):
    try:
        return tokens.set_scope(token_id, data.scope)
    except LookupError:
        raise HTTPException(status_code=404, detail="token not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/tokens/{token_id}/revoke", response_model=ApiTokenRead)
def revoke_token(token_id: UUID, tokens: ApiTokens):
    try:
        return tokens.revoke(token_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="token not found") from None


@router.post("/apps/{grant_id}/access", response_model=ConnectedAppRead)
def change_app_access(grant_id: UUID, data: AccessChange, grants: OAuthGrants):
    try:
        return grants.set_scope(grant_id, data.scope)
    except LookupError:
        raise HTTPException(status_code=404, detail="app not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None


@router.post("/apps/{grant_id}/disconnect", status_code=204)
def disconnect_app(grant_id: UUID, grants: OAuthGrants, cookie: CookieSession = Depends(require_cookie_session)):
    """Take the app's access back, and ask Supabase to stop issuing it tokens."""
    try:
        grant = grants.revoke(grant_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="app not found") from None
    oauth.revoke_grant(grant.client_id, cookie.access_token)


@consent_router.get("/consent/{authorization_id}", response_model=ConsentRead)
def consent(authorization_id: str, cookie: CookieSession = Depends(require_cookie_session)):
    """The app asking to connect (Supabase sends you to the app's consent screen with this id)."""
    try:
        details = oauth.authorization_details(authorization_id, cookie.access_token)
    except oauth.OAuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if details.redirect_url and not oauth.is_web_url(details.redirect_url):
        raise HTTPException(status_code=400, detail=NOT_A_WEB_ADDRESS)
    return ConsentRead(
        authorization_id=authorization_id,
        client_name=details.client_name,
        client_uri=details.client_uri,
        scopes=list(details.scopes),
        redirect_url=details.redirect_url,
    )


@consent_router.post("/consent/{authorization_id}", response_model=ConsentResult)
def decide(
    authorization_id: str,
    data: ConsentDecision,
    grants: OAuthGrants,
    cookie: CookieSession = Depends(require_cookie_session),
):
    """Allow (with an access level) or deny. The app recorded is whatever Supabase says this request is for."""
    approve = data.decision == "allow"
    try:
        if approve:
            details = oauth.authorization_details(authorization_id, cookie.access_token)
            grants.allow(details.client_id, details.client_name, data.access)
        redirect = oauth.decide(authorization_id, approve, cookie.access_token)
    except (oauth.OAuthError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    if not oauth.is_web_url(redirect):
        raise HTTPException(status_code=400, detail=NOT_A_WEB_ADDRESS)
    return ConsentResult(redirect_url=redirect)
