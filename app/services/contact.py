"""Contacts: the people the owner lends to, borrows from and shares expenses with.

A contact is not an account. Its ledger side is two ordinary accounts made through the account service, "Due from X"
(an asset: X owes you) and "Due to X" (a liability: you owe X), both outside the budget. What X owes in all is read
from those accounts, never stored. A contact with entries is archived rather than deleted, and only once nothing is
owed either way. The account service refuses to rename, close, delete or merge the two accounts by themselves: they
follow the contact."""

from datetime import date
from uuid import UUID

from ..config import settings
from ..limits import ensure_room
from ..models.contact import Contact
from ..models.utils import utc_now
from ..repositories.contact import ContactRepository
from ..schemas.account import AccountCreate
from ..schemas.contact import ContactCreate, ContactDeleteResult, ContactRead, ContactUpdate
from .account import AccountService

RECEIVABLE, PAYABLE = "receivable", "payable"
LAST_DAY = date(2999, 12, 31)


class ContactNotFoundError(ValueError):
    """No such contact among the person's own."""

    def __init__(self) -> None:
        super().__init__("contact not found!")


class ContactArchivedError(ValueError):
    """The contact is archived: restore it before using it again."""


class ContactInUseError(ValueError):
    """The contact cannot be archived or removed because something is still owed."""


class ContactService:
    def __init__(self, accounts: AccountService, cr: ContactRepository | None = None):
        self.accounts = accounts
        self.ar = accounts.ar
        self.cr = cr or ContactRepository(self.ar.db, self.ar.uid)
        self.db = self.ar.db

    # ---- reading -----------------------------------------------------------------------------------

    def _account_ids(self, contact_id: UUID) -> dict[str, UUID]:
        return {link.role: link.account_id for link in self.cr.links() if link.contact_id == contact_id}

    def _read(self, contact: Contact) -> ContactRead:
        ids = self._account_ids(contact.id)
        return ContactRead(
            id=contact.id,
            name=contact.name,
            email=contact.email,
            phone=contact.phone,
            notes=contact.notes,
            archived=contact.archived_at is not None,
            archived_at=contact.archived_at,
            receivable_account_id=ids[RECEIVABLE],
            payable_account_id=ids[PAYABLE],
        )

    def _get(self, contact_id: UUID) -> Contact:
        contact = self.cr.read(contact_id)
        if contact is None:
            raise ContactNotFoundError
        return contact

    def list(self, include_archived: bool = False) -> list[ContactRead]:
        """The contacts by name; archived ones only when asked."""
        contacts = [c for c in self.cr.list() if include_archived or c.archived_at is None]
        return [self._read(c) for c in sorted(contacts, key=lambda c: c.name.casefold())]

    def read(self, contact_id: UUID) -> ContactRead | None:
        contact = self.cr.read(contact_id)
        return None if contact is None else self._read(contact)

    def active(self, contact_id: UUID) -> Contact:
        """The contact for a new operation: it must exist and not be archived."""
        contact = self._get(contact_id)
        if contact.archived_at is not None:
            raise ContactArchivedError(f"'{contact.name}' is archived: restore the contact first!")
        return contact

    def owed(self, contact_id: UUID) -> dict[str, object]:
        """What the books say: `receivable` (they owe you) and `payable` (you owe them), counting entries dated ahead."""
        ids = self._account_ids(self._get(contact_id).id)
        return {role: self._balance(account_id) for role, account_id in ids.items()}

    def _balance(self, account_id: UUID):
        account = self.accounts.read(account_id, LAST_DAY)
        if account is None:
            raise ValueError("account not found!")
        return account.balance

    # ---- writing -----------------------------------------------------------------------------------

    def _check_name_free(self, name: str, exclude: UUID | None = None) -> None:
        wanted = name.casefold()
        for other in self.cr.list():
            if other.id != exclude and other.name.casefold() == wanted:
                raise ValueError(f"you already have a contact called '{other.name}'!")

    def _root(self, name: str) -> UUID:
        roots = self.accounts.ensure_roots()
        return next(a.id for a in roots if a.parent_id is None and a.name == name)

    def create(self, data: ContactCreate) -> ContactRead:
        ensure_room(len(self.cr.list()), settings.max_contacts, "contacts")
        self._check_name_free(data.name)
        try:
            contact = self.cr.add(
                Contact(user_id=self.ar.uid, name=data.name, email=data.email, phone=data.phone, notes=data.notes)
            )
            for role, root, label in ((RECEIVABLE, "Assets", "Due from"), (PAYABLE, "Liabilities", "Due to")):
                account = self.accounts.create(
                    AccountCreate(name=f"{label} {data.name}", parent_id=self._root(root), on_budget=False),
                    commit=False,
                )
                self.cr.link(contact.id, account.id, role)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(contact)

    def update(self, contact_id: UUID, data: ContactUpdate) -> ContactRead:
        contact = self._get(contact_id)
        values = data.model_dump(exclude_unset=True)
        try:
            if "name" in values and values["name"] != contact.name:
                self._check_name_free(values["name"], exclude=contact.id)
                for role, label in ((RECEIVABLE, "Due from"), (PAYABLE, "Due to")):
                    self.accounts.rename_contact_account(
                        self._account_ids(contact.id)[role], f"{label} {values['name']}"
                    )
            for key, value in values.items():
                setattr(contact, key, value)
            self.cr.save(contact)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self._read(contact)

    def _settled(self, contact: Contact) -> None:
        for role, balance in self.owed(contact.id).items():
            if balance != 0:
                raise ContactInUseError(
                    f"{contact.name} "
                    + ("owes you" if role == RECEIVABLE else "is owed by you")
                    + f" {balance:f}: settle up first!"
                )

    def archive(self, contact_id: UUID) -> ContactRead:
        """Hide the contact from new operations; its history stays. Refused while anything is owed either way."""
        contact = self._get(contact_id)
        if contact.archived_at is None:
            self._settled(contact)
            contact.archived_at = utc_now()
            self.cr.save(contact)
            self.db.commit()
        return self._read(contact)

    def restore(self, contact_id: UUID) -> ContactRead:
        contact = self._get(contact_id)
        if contact.archived_at is not None:
            contact.archived_at = None
            self.cr.save(contact)
            self.db.commit()
        return self._read(contact)

    def delete(self, contact_id: UUID) -> ContactDeleteResult:
        """Remove a contact no money ever moved with, for good. One with entries is archived instead (and only when
        nothing is owed), and the answer says which happened."""
        contact = self._get(contact_id)
        read = self._read(contact)
        ids = list(self._account_ids(contact.id).values())
        if any(self.accounts.tr.postings_for_account(account_id) for account_id in ids):
            return ContactDeleteResult(outcome="archived", contact=self.archive(contact_id))
        try:
            self.cr.delete(contact)
            for account_id in ids:
                self.accounts.delete_contact_account(account_id)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return ContactDeleteResult(outcome="deleted", contact=read)
