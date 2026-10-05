from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

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


@router.get("/login")
def login_page(request: Request, next: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": None, "email": "", "next": safe_next(next) or ""})


@router.post("/login")
def login(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "",
):
    try:
        tokens = sign_in(email.strip(), password)
    except InvalidCredentialsError:
        error, status_code = "Invalid email or password.", 401
    except AuthUnavailableError:
        error, status_code = "Sign-in is currently unavailable. Please try again later.", 503
    else:
        response = RedirectResponse(safe_next(next) or "/app/", status_code=303)
        set_auth_cookies(response, tokens)
        return response
    return templates.TemplateResponse(
        request, "login.html", {"error": error, "email": email, "next": safe_next(next) or ""}, status_code=status_code
    )


@router.post("/logout")
def logout():
    response = RedirectResponse("/app/login", status_code=303)
    clear_auth_cookies(response)
    return response
