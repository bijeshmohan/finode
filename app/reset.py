"""Forgotten passwords, through Supabase Auth.

Supabase emails a link built from its "Reset password" template; ours points at
`/reset?token_hash=...`. Opening the link only shows a form (mail scanners open
links, and the token must not be spent by them); submitting the form spends the
token and sets the new password.
"""

import httpx

from .config import settings
from .web_auth import AuthUnavailableError, SessionTokens, _to_tokens


class ResetLinkInvalidError(Exception):
    """The link was used already, has expired or is not one of ours."""


class PasswordRejectedError(Exception):
    """Supabase refused the new password; the message is safe to show."""


def _url(path: str) -> str:
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/{path}"


def _headers(token: str | None = None) -> dict[str, str]:
    headers = {"apikey": settings.supabase_anon_key or ""}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def send_reset_email(email: str) -> None:
    """Ask Supabase to email a reset link. Returns quietly whether or not the address has an account."""
    if not settings.reset_enabled:
        raise AuthUnavailableError("password reset is not configured")
    try:
        response = httpx.post(_url("recover"), json={"email": email}, headers=_headers(), timeout=10)
    except httpx.HTTPError:
        raise AuthUnavailableError("the sign-in service is unreachable") from None
    # 429 is Supabase's own limit (one email a minute per address); the caller answers the same way.
    if response.status_code not in (200, 429):
        raise AuthUnavailableError("the sign-in service returned an unexpected response")


def reset_password(token_hash: str, password: str) -> SessionTokens:
    """Spend the emailed token, set the password and return the new session."""
    if not settings.reset_enabled:
        raise AuthUnavailableError("password reset is not configured")
    try:
        verified = httpx.post(
            _url("verify"), json={"type": "recovery", "token_hash": token_hash}, headers=_headers(), timeout=10
        )
        if verified.status_code in (400, 401, 403, 404, 410, 422):
            raise ResetLinkInvalidError()
        if verified.status_code != 200:
            raise AuthUnavailableError("the sign-in service returned an unexpected response")
        tokens = _to_tokens(verified.json())
        changed = httpx.put(
            _url("user"), json={"password": password}, headers=_headers(tokens.access_token), timeout=10
        )
    except httpx.HTTPError:
        raise AuthUnavailableError("the sign-in service is unreachable") from None
    if changed.status_code in (400, 422):
        try:
            body = changed.json()
        except ValueError:
            body = {}
        raise PasswordRejectedError(str(body.get("msg") or body.get("message") or "That password was not accepted."))
    if changed.status_code != 200:
        raise AuthUnavailableError("the sign-in service returned an unexpected response")
    return tokens
