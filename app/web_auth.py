from dataclasses import dataclass

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from . import auth
from .config import settings


ACCESS_COOKIE = "finode_access"
REFRESH_COOKIE = "finode_refresh"
REFRESH_MAX_AGE = 60 * 60 * 24 * 30
LOGIN_PATH = "/app/login"


class LoginRequired(Exception):
    ...


class InvalidCredentialsError(Exception):
    ...


class AuthUnavailableError(Exception):
    ...


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
        raise AuthUnavailableError("sign-in service is unreachable")
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
    except (KeyError, TypeError, ValueError):
        raise AuthUnavailableError("sign-in service returned an unexpected response")


def sign_in(email: str, password: str) -> SessionTokens:
    return _to_tokens(_token_request("password", {"email": email, "password": password}))


def refresh_session(refresh_token: str) -> SessionTokens:
    return _to_tokens(_token_request("refresh_token", {"refresh_token": refresh_token}))


def set_auth_cookies(response: Response, tokens: SessionTokens) -> None:
    options = {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.cookie_secure,
        "path": "/app",
    }
    response.set_cookie(ACCESS_COOKIE, tokens.access_token, max_age=tokens.expires_in, **options)
    response.set_cookie(REFRESH_COOKIE, tokens.refresh_token, max_age=REFRESH_MAX_AGE, **options)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/app")
    response.delete_cookie(REFRESH_COOKIE, path="/app")


def web_login_required(request: Request) -> None:
    """Authenticate a web UI request from its cookies.

    Exposes the access token through request state so the same repositories
    and services as the JSON API can be used. An expired access token is
    renewed with the refresh token; the new cookies are written by
    refreshed_cookies_middleware.
    """
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        try:
            auth.verify_supabase_jwt(token)
        except HTTPException as e:
            if e.status_code != 401:
                raise
        else:
            request.state.access_token = token
            return

    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if refresh_token:
        try:
            tokens = refresh_session(refresh_token)
        except (InvalidCredentialsError, AuthUnavailableError):
            pass
        else:
            request.state.access_token = tokens.access_token
            request.state.refreshed_tokens = tokens
            return

    raise LoginRequired()


def login_required_handler(request: Request, exc: LoginRequired) -> Response:
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": LOGIN_PATH})
    return RedirectResponse(LOGIN_PATH, status_code=303)


async def refreshed_cookies_middleware(request: Request, call_next):
    response = await call_next(request)
    tokens = getattr(request.state, "refreshed_tokens", None)
    if tokens is not None:
        set_auth_cookies(response, tokens)
    return response
