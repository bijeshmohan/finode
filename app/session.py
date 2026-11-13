"""The Supabase session: signing in with a password, refreshing, and the HttpOnly cookies that carry it."""

from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Response

from .config import settings

ACCESS_COOKIE = "finode_access"
REFRESH_COOKIE = "finode_refresh"
REFRESH_MAX_AGE = 60 * 60 * 24 * 30


class InvalidCredentialsError(Exception): ...


class AuthUnavailableError(Exception): ...


@dataclass(frozen=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def _token_request(grant_type: str, payload: dict) -> dict:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise AuthUnavailableError("sign-in is not configured")
    try:
        response = httpx.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/token",
            params={"grant_type": grant_type},
            json=payload,
            headers={"apikey": settings.supabase_anon_key},
            timeout=10,
        )
    except httpx.HTTPError:
        raise AuthUnavailableError("sign-in service is unreachable") from None
    if response.status_code in (400, 401, 403, 422):
        raise InvalidCredentialsError()
    if response.status_code != 200:
        raise AuthUnavailableError("sign-in service returned an unexpected response")
    return response.json()


def _to_tokens(data: dict) -> SessionTokens:
    try:
        return SessionTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_in=int(data.get("expires_in", 3600)),
        )
    except KeyError, TypeError, ValueError:
        raise AuthUnavailableError("sign-in service returned an unexpected response") from None


def sign_in(email: str, password: str) -> SessionTokens:
    return _to_tokens(_token_request("password", {"email": email, "password": password}))


def refresh_session(refresh_token: str) -> SessionTokens:
    return _to_tokens(_token_request("refresh_token", {"refresh_token": refresh_token}))


def set_auth_cookies(response: Response, tokens: SessionTokens) -> None:
    options: dict[str, Any] = {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "path": "/",
    }
    response.set_cookie(ACCESS_COOKIE, tokens.access_token, max_age=tokens.expires_in, **options)
    response.set_cookie(REFRESH_COOKIE, tokens.refresh_token, max_age=REFRESH_MAX_AGE, **options)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")
