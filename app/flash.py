"""One-shot confirmation messages shown after a redirect.

The cookie only ever holds a key from MESSAGES, so nothing user-supplied is
rendered from it.
"""
from fastapi import Request, Response


FLASH_COOKIE = "finode_flash"

MESSAGES = {
    "transaction-saved": "Transaction saved",
    "transaction-saved-next": "Transaction saved. Add the next one.",
    "transaction-updated": "Transaction updated",
    "transaction-deleted": "Transaction deleted",
    "account-created": "Account added",
    "account-updated": "Account updated",
    "account-deleted": "Account deleted",
    "profile-updated": "Profile saved",
    "import-done": "Import complete",
}


def set_flash(response: Response, key: str) -> None:
    if key not in MESSAGES:
        raise ValueError(f"unknown flash message '{key}'")
    response.set_cookie(FLASH_COOKIE, key, max_age=60, httponly=True, samesite="lax", path="/app")


def flash_message(request: Request) -> str | None:
    return MESSAGES.get(request.cookies.get(FLASH_COOKIE, ""))


async def clear_shown_flash_middleware(request: Request, call_next):
    """Drop the flash cookie once a full page (which displays it) has been served."""
    response = await call_next(request)
    if (
        FLASH_COOKIE in request.cookies
        and not request.headers.get("HX-Request")
        and response.status_code == 200
        and response.headers.get("content-type", "").startswith("text/html")
    ):
        response.delete_cookie(FLASH_COOKIE, path="/app")
    return response
