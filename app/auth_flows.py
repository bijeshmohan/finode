"""The sign-in rules shared by the web pages and `/api/auth`: rate limits, checks and messages, in one place.

Each flow either returns the new session (or nothing) or raises `FlowError` with the message to show, the HTTP
status, and the seconds to wait when it is a rate limit.
"""

from dataclasses import dataclass

from sqlmodel import Session, func, select

from .config import settings
from .models.profile import Profile
from .ratelimit import attempts, minutes
from .reset import PasswordRejectedError, ResetLinkInvalidError, reset_password, send_reset_email
from .session import AuthUnavailableError, InvalidCredentialsError, SessionTokens, sign_in
from .signup import (
    EmailAlreadyRegisteredError,
    RateLimitedError,
    SignupRejectedError,
    create_user,
    invite_code_is_valid,
)

MIN_PASSWORD_LENGTH = 8


@dataclass
class FlowError(Exception):
    message: str
    status_code: int
    retry_after: int | None = None
    # "link-invalid": a spent or expired reset link (the app sends the person to "forgot password").
    code: str | None = None


def _window() -> float:
    return settings.attempt_window_minutes * 60.0


def _too_many(wait: int, what: str = "attempts") -> FlowError:
    n = minutes(wait)
    return FlowError(f"Too many {what}. Try again in {n} minute{'s' if n != 1 else ''}.", 429, retry_after=wait)


def _wait(keys: list[str], limit: int) -> int | None:
    waits = [w for w in (attempts.retry_after(k, limit, _window()) for k in keys) if w]
    return max(waits) if waits else None


def password_sign_in(client: str, email: str, password: str) -> SessionTokens:
    keys = [f"login:ip:{client}", f"login:email:{email.strip().lower()}"]
    wait = _wait(keys, settings.login_attempts)
    if wait:
        raise _too_many(wait, "sign-in attempts")
    try:
        tokens = sign_in(email.strip(), password)
    except InvalidCredentialsError:
        for k in keys:
            attempts.hit(k)
        raise FlowError("Invalid email or password.", 401) from None
    except AuthUnavailableError:
        raise FlowError("Sign-in is currently unavailable. Please try again later.", 503) from None
    attempts.reset(keys[1])
    return tokens


def _is_full(db: Session) -> bool:
    if not settings.max_users:
        return False
    return db.exec(select(func.count()).select_from(Profile)).one() >= settings.max_users


def register(
    db: Session,
    client: str,
    email: str,
    password: str,
    confirm_password: str,
    invite_code: str,
    accepted: bool,
) -> SessionTokens | None:
    """Create the account and sign in. None: the account exists but signing in failed ("Please sign in")."""
    email = email.strip()
    key = f"signup:ip:{client}"
    wait = attempts.retry_after(key, settings.signup_attempts, _window())
    if wait:
        raise _too_many(wait)
    attempts.hit(key)

    # The invite code is checked first so nothing reaches Supabase without it.
    if not invite_code_is_valid(invite_code):
        raise FlowError("Invalid invite code.", 403)
    if settings.test_notice and not accepted:
        raise FlowError("Please read the notice and tick the box to continue.", 400)
    if _is_full(db):
        raise FlowError("Registration is full for now: ask the person who invited you.", 403)
    if not email or "@" not in email:
        raise FlowError("Enter a valid email address.", 400)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise FlowError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", 400)
    if password != confirm_password:
        raise FlowError("Passwords do not match.", 400)

    try:
        create_user(email, password)
    except EmailAlreadyRegisteredError:
        raise FlowError("An account with this email already exists.", 409) from None
    except SignupRejectedError as e:
        raise FlowError(str(e), 400) from None
    except RateLimitedError:
        raise FlowError("Too many attempts. Please try again later.", 429) from None
    except AuthUnavailableError:
        raise FlowError("Sign-up is currently unavailable. Please try again later.", 503) from None

    try:
        return sign_in(email, password)
    except InvalidCredentialsError, AuthUnavailableError:
        return None


def request_reset(client: str, email: str) -> None:
    """Ask for a reset email. Succeeds the same way whether or not the address has an account."""
    email = email.strip()
    keys = [f"reset:ip:{client}", f"reset:email:{email.lower()}"]
    wait = _wait(keys, settings.reset_attempts)
    if wait:
        raise _too_many(wait)
    if not email or "@" not in email:
        raise FlowError("Enter the email address you signed up with.", 400)
    for k in keys:
        attempts.hit(k)
    try:
        send_reset_email(email)
    except AuthUnavailableError:
        raise FlowError("Could not send the email right now. Please try again later.", 503) from None


def finish_reset(client: str, token_hash: str, password: str, confirm_password: str) -> SessionTokens:
    key = f"reset-link:ip:{client}"
    wait = attempts.retry_after(key, settings.reset_attempts * 2, _window())
    if wait:
        raise _too_many(wait)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise FlowError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", 400)
    if password != confirm_password:
        raise FlowError("Passwords do not match.", 400)
    attempts.hit(key)
    try:
        return reset_password(token_hash, password)
    except ResetLinkInvalidError:
        raise FlowError(
            "That link has expired or was already used. Ask for a new one.", 400, code="link-invalid"
        ) from None
    except PasswordRejectedError as e:
        raise FlowError(str(e), 400) from None
    except AuthUnavailableError:
        raise FlowError("Could not change the password right now. Please try again later.", 503) from None
