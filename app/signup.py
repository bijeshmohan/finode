"""Invite-only sign-up: checks the invite code and creates pre-confirmed users through Supabase's admin API (service key, server side only)."""

import hashlib
import hmac

import httpx

from .config import settings
from .web_auth import AuthUnavailableError


class EmailAlreadyRegisteredError(Exception):
    ...


class SignupRejectedError(Exception):
    """Supabase refused the email or password; the message is safe to show."""


class RateLimitedError(Exception):
    ...


def invite_code_is_valid(candidate: str) -> bool:
    """Compare against the configured invite code without leaking its length or prefix."""
    if not settings.signup_code:
        return False
    expected = hashlib.sha256(settings.signup_code.encode()).digest()
    given = hashlib.sha256(candidate.encode()).digest()
    return hmac.compare_digest(expected, given)


def _admin_headers() -> dict[str, str]:
    key = settings.supabase_service_role_key or ""
    headers = {"apikey": key}
    if key.startswith("eyJ"):  # legacy JWT keys also go in Authorization
        headers["Authorization"] = f"Bearer {key}"
    return headers


def delete_user(user_id) -> None:
    """Delete a user's sign-in through Supabase's admin API (a user that is already gone counts as deleted)."""
    if not settings.can_delete_logins:
        raise AuthUnavailableError("deleting logins is not configured")
    try:
        response = httpx.delete(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users/{user_id}",
            headers=_admin_headers(),
            timeout=10,
        )
    except httpx.HTTPError:
        raise AuthUnavailableError("the sign-in service is unreachable")
    if response.status_code not in (200, 204, 404):
        raise AuthUnavailableError("the sign-in service returned an unexpected response")


def create_user(email: str, password: str) -> None:
    """Create an already-confirmed user through Supabase's admin API.

    The service key is only ever sent to Supabase from here, never to the
    browser or into logs.
    """
    if not settings.signup_enabled:
        raise AuthUnavailableError("sign-up is not configured")
    try:
        response = httpx.post(
            f"{settings.supabase_url.rstrip('/')}/auth/v1/admin/users",
            json={"email": email, "password": password, "email_confirm": True},
            headers=_admin_headers(),
            timeout=10,
        )
    except httpx.HTTPError:
        raise AuthUnavailableError("sign-up service is unreachable")

    if response.status_code in (200, 201):
        return
    if response.status_code == 429:
        raise RateLimitedError()

    try:
        body = response.json()
    except ValueError:
        body = {}
    error_code = body.get("error_code") or body.get("code")
    message = body.get("msg") or body.get("message") or body.get("error_description")

    if response.status_code in (400, 409, 422):
        if error_code in ("email_exists", "user_already_exists"):
            raise EmailAlreadyRegisteredError()
        if message:
            raise SignupRejectedError(str(message))
    # 401/403 mean the service key is wrong; do not reveal that to visitors.
    raise AuthUnavailableError("sign-up service returned an unexpected response")
