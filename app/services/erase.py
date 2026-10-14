"""Erase a person's books, or everything of theirs.

Every table that has a `user` column holds somebody's data, so the erasure walks all of them (children before
parents) instead of a list that a new feature could forget. Clearing the books keeps what belongs to the person
rather than the books: their settings (the profile) and their assistants' tokens and connections.
"""

from uuid import UUID

from sqlalchemy import delete
from sqlmodel import Session, SQLModel

from ..models.profile import Profile

# Kept when only the books are cleared.
KEPT_WITH_THE_BOOKS = {"profiles", "api_tokens", "oauth_grants"}


class EraseService:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def _erase(self, keep: set[str]) -> dict[str, int]:
        removed: dict[str, int] = {}
        try:
            for table in reversed(SQLModel.metadata.sorted_tables):
                if "user" not in table.c or table.name in keep:
                    continue
                result = self.db.execute(delete(table).where(table.c.user == self.uid))
                if result.rowcount:
                    removed[table.name] = result.rowcount
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return removed

    def erase_books(self) -> dict[str, int]:
        """Accounts, transactions, budget, recurring rules, own assets and prices, and the audit trail."""
        removed = self._erase(KEPT_WITH_THE_BOOKS)
        # A lock closes the books that were just erased: it goes with them (the rest of the profile stays).
        profile = self.db.get(Profile, self.uid)
        if profile is not None and profile.locked_through is not None:
            profile.locked_through = None
            self.db.add(profile)
            self.db.commit()
        return removed

    def erase_everything(self) -> dict[str, int]:
        """Everything of the person's in the database, settings and assistant access included."""
        return self._erase(set())
