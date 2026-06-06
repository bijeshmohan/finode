from uuid import UUID

from sqlmodel import Session, select

from ..models.journal import JournalEntry, JournalLine
from ..schemas.journal import JournalEntryCreate, JournalEntryUpdate


class JournalEntryRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def create(self, data: JournalEntryCreate) -> JournalEntry:
        values = data.model_dump(exclude={"lines"})
        entry = JournalEntry(**values, user=self.uid)
        self.db.add(entry)
        self.db.flush()
        for line_data in data.lines:
            line = JournalLine(
                **line_data.model_dump(),
                entry=entry.jid,
                user=self.uid,
            )
            self.db.add(line)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def read(self, jid: UUID) -> JournalEntry | None:
        statement = select(JournalEntry).where(
            JournalEntry.jid == jid,
            JournalEntry.user == self.uid,
        )
        entry = self.db.exec(statement).first()
        return entry

    def list(self) -> list[JournalEntry]:
        statement = select(JournalEntry).where(JournalEntry.user == self.uid)
        entries = self.db.exec(statement).all()
        return entries

    def lines(self, jid: UUID) -> list[JournalLine]:
        statement = select(JournalLine).where(
            JournalLine.entry == jid,
            JournalLine.user == self.uid,
        )
        lines = self.db.exec(statement).all()
        return lines

    def lines_for_account(self, aid: UUID) -> list[JournalLine]:
        statement = select(JournalLine).where(
            JournalLine.account == aid,
            JournalLine.user == self.uid,
        )
        lines = self.db.exec(statement).all()
        return lines

    def update(self, jid: UUID, data: JournalEntryUpdate) -> JournalEntry | None:
        entry = self.read(jid)
        if not entry:
            return None

        values = data.model_dump(exclude_unset=True, exclude={"lines"})
        for key, value in values.items():
            setattr(entry, key, value)

        if data.lines is not None:
            for line in self.lines(jid):
                self.db.delete(line)
            self.db.flush()
            for line_data in data.lines:
                line = JournalLine(
                    **line_data.model_dump(),
                    entry=entry.jid,
                    user=self.uid,
                )
                self.db.add(line)

        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def delete(self, jid: UUID) -> JournalEntry | None:
        entry = self.read(jid)
        if not entry:
            return None
        for line in self.lines(jid):
            self.db.delete(line)
        self.db.delete(entry)
        self.db.commit()
        return entry
