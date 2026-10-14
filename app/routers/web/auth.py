from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from sqlmodel import Session, func, select

from ...config import settings
from ...flash import set_flash
from ...reset import PasswordRejectedError, ResetLinkInvalidError, reset_password, send_reset_email
from ...ratelimit import attempts, minutes
from ...dependencies import get_db_session
from ...models.profile import Profile
from ...signup import (
    EmailAlreadyRegisteredError,
    RateLimitedError,
    SignupRejectedError,
    create_user,
    invite_code_is_valid,
)
from ...templating import templates
from ...web_auth import (
    AuthUnavailableError,
    InvalidCredentialsError,
    clear_auth_cookies,
    safe_next,
    set_auth_cookies,
    sign_in,
)


router = APIRouter()

DBSession = Annotated[Session, Depends(get_db_session)]

MIN_PASSWORD_LENGTH = 8


def _login_context(request: Request, error: str | None = None, email: str = "", next: str = "") -> dict:
    return {
        "error": error,
        "email": email,
        "next": safe_next(next) or "",
        "notice": "Account created. Please sign in." if request.query_params.get("created") else None,
        "signup_enabled": settings.signup_enabled,
        "reset_enabled": settings.reset_enabled,
    }


@router.get("/login")
def login_page(request: Request, next: str = ""):
    return templates.TemplateResponse(request, "login.html", _login_context(request, next=next))


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _window() -> float:
    return settings.attempt_window_minutes * 60.0


@router.post("/login")
def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "",
):
    keys = [f"login:ip:{_client(request)}", f"login:email:{email.strip().lower()}"]
    waits = [attempts.retry_after(k, settings.login_attempts, _window()) for k in keys]
    if any(waits):
        wait = max(w for w in waits if w)
        message = f"Too many sign-in attempts. Try again in {minutes(wait)} minute{'s' if minutes(wait) != 1 else ''}."
        response = templates.TemplateResponse(
            request, "login.html", _login_context(request, message, email, next), status_code=429
        )
        response.headers["Retry-After"] = str(wait)
        return response
    try:
        tokens = sign_in(email.strip(), password)
    except InvalidCredentialsError:
        for k in keys:
            attempts.hit(k)
        error, status_code = "Invalid email or password.", 401
    except AuthUnavailableError:
        error, status_code = "Sign-in is currently unavailable. Please try again later.", 503
    else:
        attempts.reset(keys[1])
        response = RedirectResponse(safe_next(next) or "/", status_code=303)
        set_auth_cookies(response, tokens)
        return response
    return templates.TemplateResponse(
        request, "login.html", _login_context(request, error, email, next), status_code=status_code
    )


def _require_signup_enabled() -> None:
    if not settings.signup_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def _signup_form(
    request: Request, error: str | None = None, email: str = "", status_code: int = 200, accepted: bool = False
):
    return templates.TemplateResponse(
        request,
        "signup.html",
        {"error": error, "email": email, "test_notice": settings.test_notice, "accepted": accepted},
        status_code=status_code,
    )


@router.get("/signup")
def signup_page(request: Request):
    _require_signup_enabled()
    return _signup_form(request)


def _is_full(db: DBSession) -> bool:
    if not settings.max_users:
        return False
    return db.exec(select(func.count()).select_from(Profile)).one() >= settings.max_users


@router.post("/signup")
def signup(
    request: Request,
    db: DBSession,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    confirm_password: Annotated[str, Form()] = "",
    invite_code: Annotated[str, Form()] = "",
    accept: Annotated[str, Form()] = "",
):
    _require_signup_enabled()
    email = email.strip()
    key = f"signup:ip:{_client(request)}"
    wait = attempts.retry_after(key, settings.signup_attempts, _window())
    if wait:
        response = _signup_form(
            request, f"Too many attempts. Try again in {minutes(wait)} minute{'s' if minutes(wait) != 1 else ''}.", email, 429
        )
        response.headers["Retry-After"] = str(wait)
        return response
    attempts.hit(key)

    # The invite code is checked first so nothing reaches Supabase without it.
    if not invite_code_is_valid(invite_code):
        return _signup_form(request, "Invalid invite code.", email, 403)
    if settings.test_notice and not accept:
        return _signup_form(request, "Please read the notice and tick the box to continue.", email, 400)
    if _is_full(db):
        return _signup_form(request, "Registration is full for now: ask the person who invited you.", email, 403)
    if not email or "@" not in email:
        return _signup_form(request, "Enter a valid email address.", email, 400)
    if len(password) < MIN_PASSWORD_LENGTH:
        return _signup_form(
            request, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", email, 400
        )
    if password != confirm_password:
        return _signup_form(request, "Passwords do not match.", email, 400)

    try:
        create_user(email, password)
    except EmailAlreadyRegisteredError:
        return _signup_form(request, "An account with this email already exists.", email, 409)
    except SignupRejectedError as e:
        return _signup_form(request, str(e), email, 400)
    except RateLimitedError:
        return _signup_form(request, "Too many attempts. Please try again later.", email, 429)
    except AuthUnavailableError:
        return _signup_form(
            request, "Sign-up is currently unavailable. Please try again later.", email, 503
        )

    try:
        tokens = sign_in(email, password)
    except (InvalidCredentialsError, AuthUnavailableError):
        return RedirectResponse("/login?created=1", status_code=303)
    response = RedirectResponse("/", status_code=303)
    set_auth_cookies(response, tokens)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    clear_auth_cookies(response)
    return response


# ---- forgotten password -------------------------------------------------------------------------------------


def _require_reset_enabled() -> None:
    if not settings.reset_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def _forgot_form(request: Request, error: str | None = None, email: str = "", sent: bool = False, status_code: int = 200):
    return templates.TemplateResponse(
        request, "forgot.html", {"error": error, "email": email, "sent": sent}, status_code=status_code
    )


@router.get("/forgot")
def forgot_page(request: Request):
    _require_reset_enabled()
    return _forgot_form(request)


@router.post("/forgot")
def forgot(request: Request, email: Annotated[str, Form()] = ""):
    _require_reset_enabled()
    email = email.strip()
    keys = [f"reset:ip:{_client(request)}", f"reset:email:{email.lower()}"]
    waits = [attempts.retry_after(k, settings.reset_attempts, _window()) for k in keys]
    if any(waits):
        wait = max(w for w in waits if w)
        response = _forgot_form(
            request, f"Too many attempts. Try again in {minutes(wait)} minute{'s' if minutes(wait) != 1 else ''}.", email,
            status_code=429,
        )
        response.headers["Retry-After"] = str(wait)
        return response
    if not email or "@" not in email:
        return _forgot_form(request, "Enter the email address you signed up with.", email, status_code=400)
    for k in keys:
        attempts.hit(k)
    try:
        send_reset_email(email)
    except AuthUnavailableError:
        return _forgot_form(request, "Could not send the email right now. Please try again later.", email, status_code=503)
    # The same answer whether or not the address has an account, so this cannot be used to find out who does.
    return _forgot_form(request, email=email, sent=True)


def _reset_form(request: Request, token_hash: str, error: str | None = None, status_code: int = 200):
    return templates.TemplateResponse(
        request, "reset.html", {"error": error, "token_hash": token_hash}, status_code=status_code
    )


@router.get("/reset")
def reset_page(request: Request, token_hash: str = ""):
    _require_reset_enabled()
    if not token_hash:
        return _forgot_form(request, "That link is not valid. Ask for a new one.", status_code=400)
    return _reset_form(request, token_hash)


@router.post("/reset")
def reset(
    request: Request,
    token_hash: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    confirm_password: Annotated[str, Form()] = "",
):
    _require_reset_enabled()
    key = f"reset-link:ip:{_client(request)}"
    wait = attempts.retry_after(key, settings.reset_attempts * 2, _window())
    if wait:
        response = _reset_form(request, token_hash, f"Too many attempts. Try again in {minutes(wait)} minute{'s' if minutes(wait) != 1 else ''}.", 429)
        response.headers["Retry-After"] = str(wait)
        return response
    if len(password) < MIN_PASSWORD_LENGTH:
        return _reset_form(request, token_hash, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", 400)
    if password != confirm_password:
        return _reset_form(request, token_hash, "Passwords do not match.", 400)
    attempts.hit(key)
    try:
        tokens = reset_password(token_hash, password)
    except ResetLinkInvalidError:
        return _forgot_form(request, "That link has expired or was already used. Ask for a new one.", status_code=400)
    except PasswordRejectedError as e:
        return _reset_form(request, token_hash, str(e), 400)
    except AuthUnavailableError:
        return _reset_form(request, token_hash, "Could not change the password right now. Please try again later.", 503)
    response = RedirectResponse("/", status_code=303)
    set_auth_cookies(response, tokens)
    set_flash(response, "password-reset")
    return response
