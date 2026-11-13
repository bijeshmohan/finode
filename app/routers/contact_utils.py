"""What the routes for people share (contacts, shared expenses, shared income): the retry header and how a refusal is
answered."""

from typing import Annotated

from fastapi import Header, HTTPException

from ..services.contact_errors import ConflictError, NotFoundError

IdempotencyKey = Annotated[
    str | None,
    Header(
        max_length=100,
        description="Send the same key again after a timeout and the first result comes back instead of a second entry.",
    ),
]


def refused(e: ValueError) -> HTTPException:
    """404 for something that is not the person's, 409 for a clash with what was already done, 400 for the rest."""
    status = 404 if isinstance(e, NotFoundError) else 409 if isinstance(e, ConflictError) else 400
    return HTTPException(status_code=status, detail=str(e))
