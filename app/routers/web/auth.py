"""Signing in, signing up, signing out and resetting a password (the only pages open to someone not signed in).

The rules and messages live in `app/auth_flows.py`, shared with `/api/auth`; these routes only draw the pages."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from ...auth_flows import FlowError, finish_reset, password_sign_in, register, request_reset
from ...config import settings
from ...dependencies import get_db_session
from ...flash import set_flash
from ...ratelimit import client_address
from ...session import clear_auth_cookies, set_auth_cookies
from ...templating import templates
from ...web_auth import safe_next

router = APIRouter()

DBSession = Annotated[Session, Depends(get_db_session)]


def _login_context(request: Request, error: str | None = None, email: str = "", next: str = "") -> dict:
    return {
        "error": error,
        "email": email,
        "next": safe_next(next) or "",
        "notice": "Account created. Please sign in." if request.query_params.get("created") else None,
        "signup_enabled": settings.signup_enabled,
        "reset_enabled": settings.reset_enabled,
    }


def _with_wait(response: Response, e: FlowError) -> Response:
    if e.retry_after:
        response.headers["Retry-After"] = str(e.retry_after)
    return response


@router.get("/login")
def login_page(request: Request, next: str = ""):
    return templates.TemplateResponse(request, "login.html", _login_context(request, next=next))


@router.post("/login")
def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "",
):
    try:
        tokens = password_sign_in(client_address(request), email, password)
    except FlowError as e:
        response = templates.TemplateResponse(
            request, "login.html", _login_context(request, e.message, email, next), status_code=e.status_code
        )
        return _with_wait(response, e)
    redirect = RedirectResponse(safe_next(next) or "/", status_code=303)
    set_auth_cookies(redirect, tokens)
    return redirect


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
    try:
        tokens = register(
            db, client_address(request), email, password, confirm_password, invite_code, accepted=bool(accept)
        )
    except FlowError as e:
        return _with_wait(_signup_form(request, e.message, email.strip(), e.status_code), e)
    if tokens is None:
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


def _forgot_form(
    request: Request, error: str | None = None, email: str = "", sent: bool = False, status_code: int = 200
):
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
    try:
        request_reset(client_address(request), email)
    except FlowError as e:
        return _with_wait(_forgot_form(request, e.message, email.strip(), status_code=e.status_code), e)
    # The same answer whether or not the address has an account, so this cannot be used to find out who does.
    return _forgot_form(request, email=email.strip(), sent=True)


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
    try:
        tokens = finish_reset(client_address(request), token_hash, password, confirm_password)
    except FlowError as e:
        if e.code == "link-invalid":
            return _forgot_form(request, e.message, status_code=e.status_code)
        return _with_wait(_reset_form(request, token_hash, e.message, e.status_code), e)
    response = RedirectResponse("/", status_code=303)
    set_auth_cookies(response, tokens)
    set_flash(response, "password-reset")
    return response
