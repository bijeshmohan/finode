"""The period lock: the books are closed up to a day the person chose.

Nothing dated on or before `profiles.locked_through` can be added, changed or deleted by hand, and the budget
of a month that ends inside the lock cannot be changed either. Recurring rules skip occurrences that fall in it.
Imports and restores only fill an empty ledger and are not held up by it.
"""
from datetime import date
from uuid import UUID

from sqlmodel import Session, select

from ..models.profile import Profile


class LockedPeriodError(ValueError):
    """A change that reaches into the locked period."""


def locked_through(db: Session, uid: UUID) -> date | None:
    return db.exec(select(Profile.locked_through).where(Profile.user == uid)).first()


def refuse_locked(db: Session, uid: UUID, *days: date | None) -> None:
    """Raise LockedPeriodError when any of the days is on or before the lock."""
    lock = locked_through(db, uid)
    if lock is None:
        return
    for day in days:
        if day is not None and day <= lock:
            raise LockedPeriodError(
                f"{day:%d %b %Y} is in a locked period (everything up to {lock:%d %b %Y} is closed): "
                "move or remove the lock under Settings to change it!"
            )
