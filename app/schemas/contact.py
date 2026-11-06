import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

MAX_NAME = 30  # "Due from " takes 9 of an account name's 40 characters


def clean_contact_name(value: str) -> str:
    """A contact's name as kept: trimmed, visible, on one line, without ':' (it becomes part of two account names)."""
    value = value.strip()
    if not value or all(unicodedata.category(c) in ("Cf", "Zs", "Zl", "Zp") for c in value):
        raise ValueError("name must not be empty!")
    if any(unicodedata.category(c) == "Cc" for c in value):
        raise ValueError("name must be on one line, without control characters!")
    if ":" in value:
        raise ValueError("name must not contain ':'!")
    return value


def _tidy(value: str | None) -> str | None:
    """A blank detail is none."""
    return (value or "").strip() or None


class ContactBase(BaseModel):
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("email", "phone", "notes")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return _tidy(value)


class ContactCreate(ContactBase):
    name: str = Field(max_length=MAX_NAME)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        return clean_contact_name(value)


class ContactUpdate(ContactBase):
    # Only what is sent changes; null clears email, phone and notes.
    name: str | None = Field(default=None, max_length=MAX_NAME)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name must not be empty!")
        return clean_contact_name(value)


class ContactRead(ContactBase):
    id: UUID
    name: str
    archived: bool
    archived_at: datetime | None
    # The ledger accounts behind the contact: "Due from X" (they owe you) and "Due to X" (you owe them).
    receivable_account_id: UUID
    payable_account_id: UUID


class ContactDeleteResult(BaseModel):
    # "deleted" (no money ever moved: gone for good) or "archived" (it has history: kept, no longer offered).
    outcome: Literal["deleted", "archived"]
    contact: ContactRead
