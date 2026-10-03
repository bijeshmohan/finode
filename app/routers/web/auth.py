from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ...config import settings
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
    set_auth_cookies,
    sign_in,
)


router = APIRouter()

MIN_PASSWORD_LENGTH = 8


def _login_context(request: Request, error: str | None = None, email: str = "") -> dict:
    return {
        "error": error,
        "email": email,
        "notice": "Account created. Please sign in." if request.query_params.get("created") else None,
        "signup_enabled": settings.signup_enabled,
    }


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", _login_context(request))


@router.post("/login")
def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    try:
        tokens = sign_in(email.strip(), password)
    except InvalidCredentialsError:
        error, status_code = "Invalid email or password.", 401
    except AuthUnavailableError:
        error, status_code = "Sign-in is currently unavailable. Please try again later.", 503
    else:
        response = RedirectResponse("/app/", status_code=303)
        set_auth_cookies(response, tokens)
        return response
    return templates.TemplateResponse(
        request, "login.html", _login_context(request, error, email), status_code=status_code
    )


def _require_signup_enabled() -> None:
    if not settings.signup_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def _signup_form(request: Request, error: str | None = None, email: str = "", status_code: int = 200):
    return templates.TemplateResponse(
        request, "signup.html", {"error": error, "email": email}, status_code=status_code
    )


@router.get("/signup")
def signup_page(request: Request):
    _require_signup_enabled()
    return _signup_form(request)


@router.post("/signup")
def signup(
    request: Request,
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    confirm_password: Annotated[str, Form()] = "",
    invite_code: Annotated[str, Form()] = "",
):
    _require_signup_enabled()
    email = email.strip()

    # The invite code is checked first so nothing reaches Supabase without it.
    if not invite_code_is_valid(invite_code):
        return _signup_form(request, "Invalid invite code.", email, 403)
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
        return RedirectResponse("/app/login?created=1", status_code=303)
    response = RedirectResponse("/app/", status_code=303)
    set_auth_cookies(response, tokens)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse("/app/login", status_code=303)
    clear_auth_cookies(response)
    return response
