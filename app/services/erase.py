"""Erase a person's books, or everything of theirs.

Every table that has a `user_id` column holds somebody's data, so the erasure walks all of them (children before
parents) instead of a list that a new feature could forget. Clearing the books keeps what belongs to the person
rather than the books: their settings (the profile) and their assistants' tokens and connections.
"""

from typing import cast
from uuid import UUID

from sqlalchemy import CursorResult, delete
from sqlmodel import Session, SQLModel

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
                if "user_id" not in table.c or table.name in keep:
                    continue
                result = self.db.execute(delete(table).where(table.c.user_id == self.uid))
                count = cast(CursorResult, result).rowcount  # a DELETE returns a CursorResult
                if count:
                    removed[table.name] = count
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return removed

    def erase_books(self) -> dict[str, int]:
        """Accounts, transactions, budget, recurring rules and the audit trail."""
        removed = self._erase(KEPT_WITH_THE_BOOKS)
        return removed

    def erase_everything(self) -> dict[str, int]:
        """Everything of the person's in the database, settings and assistant access included."""
        return self._erase(set())
