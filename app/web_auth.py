"""The web pages' sign-in guard: a page needs the session cookies (see app/session.py), refreshed when they expire."""

from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from . import auth
from .session import set_auth_cookies

LOGIN_PATH = "/login"


class LoginRequired(Exception): ...


def web_login_required(request: Request) -> None:
    """Authenticate a web UI request from its cookies.

    Exposes the access token through request state so the same repositories
    and services as the JSON API can be used. An expired access token is
    renewed with the refresh token; the new cookies are written by
    refreshed_cookies_middleware.
    """
    token = auth.token_from_cookies(request)
    if token is None:
        raise LoginRequired()
    request.state.access_token = token


CONSENT_PATH = "/oauth/consent"


def safe_next(target: str | None) -> str | None:
    """Where to go after signing in: only the OAuth consent page, which an app sends people to."""
    if target and target.startswith(CONSENT_PATH) and target[len(CONSENT_PATH) : len(CONSENT_PATH) + 1] in ("", "?"):
        return target
    return None


def login_required_handler(request: Request, exc: LoginRequired) -> Response:
    if request.headers.get("HX-Request"):
        return Response(status_code=401, headers={"HX-Redirect": LOGIN_PATH})
    if request.method == "GET" and request.url.path == CONSENT_PATH:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"{LOGIN_PATH}?{urlencode({'next': target})}", status_code=303)
    return RedirectResponse(LOGIN_PATH, status_code=303)


async def refreshed_cookies_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]):
    response = await call_next(request)
    tokens = getattr(request.state, "refreshed_tokens", None)
    if tokens is not None:
        set_auth_cookies(response, tokens)
    return response
