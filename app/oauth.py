"""Talking to Supabase's OAuth 2.1 server on the user's behalf (the consent step).

Supabase registers the apps, issues their tokens and asks us, through a consent page, whether the
signed-in user allows an app. These calls use the *user's own* session token, as supabase-js's
`auth.oauth.*` methods do.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from .config import settings


class OAuthError(Exception):
    """Supabase refused, or could not be reached; the message is fit to show the user."""


@dataclass(frozen=True)
class AuthorizationDetails:
    authorization_id: str
    client_id: str
    client_name: str
    client_uri: str | None
    redirect_uri: str | None
    scopes: tuple[str, ...]
    # Set when the user already decided and Supabase just wants them sent back to the app.
    redirect_url: str | None = None


def auth_url() -> str:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise OAuthError("sign-in is not configured")
    return f"{settings.supabase_url.rstrip('/')}/auth/v1"


def issuer() -> str:
    return auth_url()


def _headers(user_token: str) -> dict[str, str]:
    return {"apikey": settings.supabase_anon_key or "", "Authorization": f"Bearer {user_token}"}


def _call(method: str, path: str, user_token: str, **kwargs) -> dict:
    try:
        response = httpx.request(method, f"{auth_url()}{path}", headers=_headers(user_token), timeout=10, **kwargs)
    except httpx.HTTPError:
        raise OAuthError("the sign-in service is unreachable: try again in a moment!")
    if response.status_code in (401, 403):
        raise OAuthError("your sign-in has expired: sign in again and retry!")
    if response.status_code == 404:
        raise OAuthError("this authorization request is unknown or has expired: start again from the app!")
    if response.status_code >= 400:
        try:
            message = response.json().get("msg") or response.json().get("error_description")
        except ValueError:
            message = None
        raise OAuthError(message or "the sign-in service refused the request!")
    try:
        return response.json() if response.content else {}
    except ValueError:
        raise OAuthError("the sign-in service returned an unexpected response!")


def authorization_details(authorization_id: str, user_token: str) -> AuthorizationDetails:
    data = _call("GET", f"/oauth/authorizations/{authorization_id}", user_token)
    client = data.get("client") or {}
    return AuthorizationDetails(
        authorization_id=authorization_id,
        client_id=str(client.get("id") or data.get("client_id") or ""),
        client_name=str(client.get("name") or "An app"),
        client_uri=client.get("uri"),
        redirect_uri=data.get("redirect_uri"),
        scopes=tuple((data.get("scope") or "").split()),
        redirect_url=data.get("redirect_url"),
    )


def decide(authorization_id: str, approve: bool, user_token: str) -> str:
    """Approve or deny; returns where to send the user next (back to the app)."""
    data = _call(
        "POST",
        f"/oauth/authorizations/{authorization_id}/consent",
        user_token,
        json={"action": "approve" if approve else "deny"},
    )
    url = data.get("redirect_url")
    if not url:
        raise OAuthError("the sign-in service did not say where to go next!")
    return url


def revoke_grant(client_id: str, user_token: str) -> None:
    """Stop Supabase issuing and refreshing tokens for the app. Best effort: finode's own check is what blocks it."""
    try:
        _call("DELETE", "/user/oauth/grants", user_token, params={"client_id": client_id})
    except OAuthError:
        pass


def is_web_url(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https")
