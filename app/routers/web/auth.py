from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ...templating import templates
from ...web_auth import (
    AuthUnavailableError,
    InvalidCredentialsError,
    clear_auth_cookies,
    set_auth_cookies,
    sign_in,
)


router = APIRouter()


@router.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None, "email": ""})


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
        request, "login.html", {"error": error, "email": email}, status_code=status_code
    )


@router.post("/logout")
def logout():
    response = RedirectResponse("/app/login", status_code=303)
    clear_auth_cookies(response)
    return response
