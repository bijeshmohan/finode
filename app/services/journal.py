from uuid import UUID

from ..models.journal import JournalEntry, JournalLine
from ..repositories import AccountRepository, JournalEntryRepository
from ..schemas.journal import (
    JournalEntryCreate,
    JournalEntryRead,
    JournalEntryUpdate,
    JournalLineRead,
)


class JournalEntryService:
    def __init__(self, jr: JournalEntryRepository, ar: AccountRepository):
        self.jr = jr
        self.ar = ar

    def _validate_references(
        self,
        data: JournalEntryCreate | JournalEntryUpdate,
    ) -> None:
        lines = data.lines
        if lines is None:
            return
        for line in lines:
            if not self.ar.read(line.account):
                raise ValueError(f"account with aid '{line.account}' not found!")

    def _line_to_read(self, line: JournalLine) -> JournalLineRead:
        return JournalLineRead(
            lid=line.lid,
            entry=line.entry,
            account=line.account,
            side=line.side,
            amount=line.amount,
            created=line.created,
            updated=line.updated,
        )

    def _to_read(self, entry: JournalEntry) -> JournalEntryRead:
        return JournalEntryRead(
            jid=entry.jid,
            date=entry.date,
            note=entry.note,
            details=entry.details,
            lines=[self._line_to_read(line) for line in self.jr.lines(entry.jid)],
            created=entry.created,
            updated=entry.updated,
        )

    def create(self, data: JournalEntryCreate) -> JournalEntryRead:
        self._validate_references(data)
        entry = self.jr.create(data)
        return self._to_read(entry)

    def read(self, jid: UUID) -> JournalEntryRead | None:
        entry = self.jr.read(jid)
        if not entry:
            return None
        return self._to_read(entry)

    def list(self) -> list[JournalEntryRead]:
        return [self._to_read(entry) for entry in self.jr.list()]

    def update(
        self,
        jid: UUID,
        data: JournalEntryUpdate,
    ) -> JournalEntryRead | None:
        if not self.jr.read(jid):
            raise ValueError(f"journal entry with jid '{jid}' not found!")
        self._validate_references(data)
        entry = self.jr.update(jid, data)
        if not entry:
            raise RuntimeError(f"failed to update journal entry with jid '{jid}'!")
        return self._to_read(entry)

    def delete(self, jid: UUID) -> JournalEntryRead | None:
        entry = self.read(jid)
        deleted = self.jr.delete(jid)
        if not deleted:
            raise ValueError(f"journal entry with jid '{jid}' not found!")
        return entry
