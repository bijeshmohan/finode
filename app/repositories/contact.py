"""Persistence for contacts and the accounts behind them, always filtered by the user's id."""

import builtins
from uuid import UUID

from sqlmodel import Session, select

from ..models.contact import Contact, ContactAccount
from .cache import remembered


class ContactRepository:
    def __init__(self, db: Session, uid: UUID):
        self.db = db
        self.uid = uid

    def list(self) -> builtins.list[Contact]:
        """Every contact of the person (archived ones too), loaded once per session (see repositories/cache.py)."""
        statement = select(Contact).where(Contact.user_id == self.uid)
        return list(remembered(self.db, ("contacts", self.uid), lambda: self.db.exec(statement).all()))

    def read(self, contact_id: UUID) -> Contact | None:
        return next((c for c in self.list() if c.id == contact_id), None)

    def links(self) -> builtins.list[ContactAccount]:
        """The account links of every contact, loaded once per session."""
        statement = select(ContactAccount).where(ContactAccount.user_id == self.uid)
        return list(remembered(self.db, ("contact_links", self.uid), lambda: self.db.exec(statement).all()))

    def add(self, contact: Contact) -> Contact:
        self.db.add(contact)
        self.db.flush()
        return contact

    def link(self, contact_id: UUID, account_id: UUID, role: str) -> ContactAccount:
        link = ContactAccount(user_id=self.uid, contact_id=contact_id, account_id=account_id, role=role)
        self.db.add(link)
        self.db.flush()
        return link

    def save(self, contact: Contact) -> Contact:
        self.db.add(contact)
        self.db.flush()
        return contact

    def delete(self, contact: Contact) -> None:
        """Remove the contact and its links (the accounts are the caller's to remove)."""
        for link in self.links():
            if link.contact_id == contact.id:
                self.db.delete(link)
        self.db.flush()
        self.db.delete(contact)
        self.db.flush()
