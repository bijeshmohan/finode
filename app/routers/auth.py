"""JSON API for signing in (`/api/auth`): the finode app's sign-in, sign-up, password reset, sign-out and session.

The session lives in HttpOnly cookies set here; the app's JavaScript never holds a token. Every POST must come from the
app (`auth.check_app_request`). The rules and messages are the web pages' own (`app/auth_flows.py`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlmodel import Session

from ..auth import CurrentUser, check_app_request, require_authenticated_user
from ..auth_flows import FlowError, finish_reset, password_sign_in, register, request_reset
from ..clock import local_today
from ..config import settings
from ..dependencies import get_db_session
from ..feedback import feedback_url
from ..ratelimit import client_address
from ..schemas.auth import AuthOptions, ForgotPassword, ResetPassword, SessionRead, SignIn, SignUp, SignUpResult
from ..session import clear_auth_cookies, set_auth_cookies

router = APIRouter(prefix="/auth", tags=["auth"])
from_the_app = [Depends(check_app_request)]


def _refused(e: FlowError) -> HTTPException:
    headers = {"Retry-After": str(e.retry_after)} if e.retry_after else None
    return HTTPException(status_code=e.status_code, detail={"message": e.message, "code": e.code}, headers=headers)


@router.get("/options", response_model=AuthOptions)
def options():
    """What the sign-in screens offer here: sign-up (invite only), forgotten password, the test notice."""
    return AuthOptions(
        signup_enabled=settings.signup_enabled, reset_enabled=settings.reset_enabled, test_notice=settings.test_notice
    )


@router.get("/session", response_model=SessionRead)
def session(user: Annotated[CurrentUser, Depends(require_authenticated_user)]):
    """Who is signed in, and today's date as finode counts it."""
    return SessionRead(
        email=user.email,
        today=local_today(),
        feedback_url=feedback_url(),
        can_delete_login=settings.can_delete_logins,
    )


@router.post("/sign-in", status_code=204, dependencies=from_the_app)
def sign_in(data: SignIn, request: Request, response: Response):
    try:
        tokens = password_sign_in(client_address(request), data.email, data.password)
    except FlowError as e:
        raise _refused(e) from None
    set_auth_cookies(response, tokens)


@router.post("/sign-up", status_code=201, response_model=SignUpResult, dependencies=from_the_app)
def sign_up(data: SignUp, request: Request, response: Response, db: Annotated[Session, Depends(get_db_session)]):
    """Invite-only: 404 unless sign-up is set up on this server."""
    if not settings.signup_enabled:
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        tokens = register(
            db, client_address(request), data.email, data.password, data.confirm_password, data.invite_code, data.accept
        )
    except FlowError as e:
        raise _refused(e) from None
    if tokens is not None:
        set_auth_cookies(response, tokens)
    return SignUpResult(signed_in=tokens is not None)


def _require_reset() -> None:
    if not settings.reset_enabled:
        raise HTTPException(status_code=404, detail="Not Found")


@router.post("/forgot", status_code=202, dependencies=[*from_the_app, Depends(_require_reset)])
def forgot(data: ForgotPassword, request: Request):
    """Email a reset link. The same answer whether or not the address has an account."""
    try:
        request_reset(client_address(request), data.email)
    except FlowError as e:
        raise _refused(e) from None


@router.post("/reset", status_code=204, dependencies=[*from_the_app, Depends(_require_reset)])
def reset(data: ResetPassword, request: Request, response: Response):
    """Set a new password from the emailed link and sign in. A spent or expired link answers `code: link-invalid`."""
    try:
        tokens = finish_reset(client_address(request), data.token_hash, data.password, data.confirm_password)
    except FlowError as e:
        raise _refused(e) from None
    set_auth_cookies(response, tokens)


@router.post("/sign-out", status_code=204, dependencies=from_the_app)
def sign_out(response: Response):
    clear_auth_cookies(response)
