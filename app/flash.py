"""One-shot confirmation messages shown after a redirect.

The cookie only ever holds a key from MESSAGES, so nothing user-supplied is
rendered from it.
"""
from uuid import UUID

from fastapi import Request, Response


FLASH_COOKIE = "finode_flash"

MESSAGES = {
    "password-reset": "Your password was changed. You are signed in.",
    "budget-moved": "Money moved",
    "books-erased": "Your books were erased",
    "your-account-deleted": "Your account was deleted. Goodbye!",
    "restore-done": "Backup restored",
    "account-closed": "Account closed",
    "groups-added": "Standard groups added",
    "goal-created": "Goal created",
    "goal-saved": "Goal saved",
    "goal-deleted": "Goal deleted",
    "account-moved": "Moved",
    "account-order-reset": "Back in alphabetical order",
    "account-reopened": "Account reopened",
    "account-restored": "Account restored",
    "lock-saved": "Locked: nothing up to that day can be changed",
    "lock-removed": "Lock removed",
    "recurring-saved": "Recurring transaction saved. Anything already due has been recorded.",
    "recurring-paused": "Paused. Nothing will be recorded until you resume it.",
    "recurring-skipped": "Skipped. Nothing was recorded for that one; the next one is on its way as usual.",
    "recurring-resumed": "Resumed. Occurrences missed while it was paused are skipped.",
    "recurring-deleted": "Recurring transaction deleted. What it recorded is kept.",
    "transaction-saved": "Transaction saved",
    "transaction-saved-next": "Transaction saved. Add the next one.",
    "transaction-updated": "Transaction updated",
    "transaction-deleted": "Transaction deleted",
    "transaction-restored": "Transaction restored",
    "account-created": "Account added",
    "account-updated": "Account updated",
    "account-deleted": "Account deleted",
    "category-deleted": "Category deleted",
    "category-restored": "Category restored",
    "profile-updated": "Profile saved",
    "import-done": "Import complete",
    "currency-updated": "Currency saved",
    "app-disconnected": "App disconnected. It can no longer reach your books.",
    "access-changed": "Access updated. It applies to the very next request.",
    "token-revoked": "Token revoked. Assistants using it can no longer connect.",
}


UNDO_KINDS = {"restore": "/transactions/deleted/{}/restore", "delete": "/transactions/{}/delete"}


def set_flash(response: Response, key: str, undo: tuple[str, UUID] | None = None) -> None:
    """`undo` is ("restore", hid) or ("delete", tid): the toast then carries an Undo button for that one action."""
    if key not in MESSAGES:
        raise ValueError(f"unknown flash message '{key}'")
    value = key if undo is None else f"{key}|{undo[0]}|{undo[1]}"
    response.set_cookie(FLASH_COOKIE, value, max_age=60, httponly=True, samesite="lax", path="/")


def _parts(request: Request) -> list[str]:
    return request.cookies.get(FLASH_COOKIE, "").split("|")


def flash_message(request: Request) -> str | None:
    return MESSAGES.get(_parts(request)[0])


def flash_undo(request: Request) -> str | None:
    """The address the toast's Undo button posts to, rebuilt from a kind and a UUID (nothing else is ever trusted)."""
    parts = _parts(request)
    if len(parts) != 3 or parts[0] not in MESSAGES or parts[1] not in UNDO_KINDS:
        return None
    try:
        return UNDO_KINDS[parts[1]].format(UUID(parts[2]))
    except ValueError:
        return None


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
