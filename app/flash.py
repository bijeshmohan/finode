"""One-shot confirmation messages shown after a redirect.

The cookie only ever holds a key from MESSAGES, so nothing user-supplied is
rendered from it.
"""
from fastapi import Request, Response


FLASH_COOKIE = "finode_flash"

MESSAGES = {
    "budget-moved": "Money moved",
    "recurring-saved": "Recurring transaction saved. Anything already due has been recorded.",
    "recurring-paused": "Paused. Nothing will be recorded until you resume it.",
    "recurring-resumed": "Resumed. Occurrences missed while it was paused are skipped.",
    "recurring-deleted": "Recurring transaction deleted. What it recorded is kept.",
    "transaction-saved": "Transaction saved",
    "transaction-saved-next": "Transaction saved. Add the next one.",
    "transaction-updated": "Transaction updated",
    "transaction-deleted": "Transaction deleted",
    "account-created": "Account added",
    "account-updated": "Account updated",
    "account-deleted": "Account deleted",
    "profile-updated": "Profile saved",
    "import-done": "Import complete",
    "depth-updated": "Account depth saved",
    "currency-updated": "Default currency saved",
    "commodity-added": "Commodity added",
    "commodity-deleted": "Commodity removed",
    "price-saved": "Price saved",
    "price-deleted": "Price removed",
    "app-disconnected": "App disconnected. It can no longer reach your books.",
    "access-changed": "Access updated. It applies to the very next request.",
    "token-revoked": "Token revoked. Assistants using it can no longer connect.",
}


def set_flash(response: Response, key: str) -> None:
    if key not in MESSAGES:
        raise ValueError(f"unknown flash message '{key}'")
    response.set_cookie(FLASH_COOKIE, key, max_age=60, httponly=True, samesite="lax", path="/")


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
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response
