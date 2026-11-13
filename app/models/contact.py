"""People: contacts, the accounts that stand for them, what is owed either way, settlements and shared expenses."""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

from .utils import Amount, TimestampMixin, utc_now


class Contact(TimestampMixin, table=True):
    """A person the owner has money dealings with. Not an account: the ledger side is the two accounts in
    `contact_accounts`. Archiving hides a contact and keeps everything it did."""

    __tablename__ = "contacts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(index=True, foreign_key="auth.users.id")
    name: str = Field(max_length=30)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=500)
    archived_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class ContactAccount(SQLModel, table=True):
    """The ledger accounts that stand for a contact: "Due from X" (an asset, the contact owes the owner) and
    "Due to X" (a liability, the owner owes the contact)."""

    __tablename__ = "contact_accounts"
    __table_args__ = (
        UniqueConstraint("contact_id", "role", name="uq_contact_accounts_contact_role"),
        UniqueConstraint("account_id", name="uq_contact_accounts_account"),
        CheckConstraint("role IN ('receivable', 'payable')", name="ck_contact_accounts_role"),
        Index("ix_contact_accounts_user", "user_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    contact_id: UUID = Field(foreign_key="contacts.id")
    account_id: UUID = Field(foreign_key="accounts.id")
    role: str = Field(max_length=10)
    created: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))


class PartyTransaction(SQLModel, table=True):
    """Ties a ledger entry to a contact for the contact's activity (a loan, a gift, a share of an expense, a
    settlement). Entries with a row here belong to the contact services: the generic edit and delete refuse them."""

    __tablename__ = "party_transactions"
    __table_args__ = (
        UniqueConstraint("contact_id", "transaction_id", name="uq_party_transactions_contact_transaction"),
        CheckConstraint(
            "purpose IN ('loan', 'borrowing', 'advance', 'gift', 'expense', 'settlement', 'opening', 'netoff', 'income')",
            name="ck_party_transactions_purpose",
        ),
        CheckConstraint("direction IN ('sent', 'received')", name="ck_party_transactions_direction"),
        Index("ix_party_transactions_user", "user_id"),
        Index("ix_party_transactions_transaction", "transaction_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    contact_id: UUID = Field(foreign_key="contacts.id")
    transaction_id: UUID = Field(foreign_key="transactions.id")
    purpose: str = Field(max_length=10)
    direction: str = Field(max_length=8)
    created: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))


class PartyObligation(SQLModel, table=True):
    """One amount a contact owes the owner (receivable) or the owner owes the contact (payable). It never changes: how
    much is still owed is the amount less the settlements against it. Always made together with its ledger entry."""

    __tablename__ = "party_obligations"
    __table_args__ = (
        CheckConstraint("original_amount > 0", name="ck_party_obligations_amount"),
        CheckConstraint("direction IN ('receivable', 'payable')", name="ck_party_obligations_direction"),
        CheckConstraint(
            "source_type IN ('shared_expense', 'shared_income', 'loan', 'borrowing', 'advance', 'opening')",
            name="ck_party_obligations_source",
        ),
        Index("ix_party_obligations_user", "user_id"),
        Index("ix_party_obligations_contact", "contact_id"),
        Index("ix_party_obligations_source", "source_transaction_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    contact_id: UUID = Field(foreign_key="contacts.id")
    source_transaction_id: UUID = Field(foreign_key="transactions.id")
    source_type: str = Field(max_length=14)
    direction: str = Field(max_length=10)
    original_amount: Decimal = Field(sa_type=Amount())
    created: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))


class ObligationSettlement(SQLModel, table=True):
    """Part of a settlement entry that clears (part of) an obligation. An obligation may be cleared by several entries
    and an entry may clear several obligations."""

    __tablename__ = "obligation_settlements"
    __table_args__ = (
        UniqueConstraint("obligation_id", "settlement_transaction_id", name="uq_obligation_settlements_pair"),
        CheckConstraint("amount > 0", name="ck_obligation_settlements_amount"),
        Index("ix_obligation_settlements_user", "user_id"),
        Index("ix_obligation_settlements_transaction", "settlement_transaction_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    obligation_id: UUID = Field(foreign_key="party_obligations.id")
    settlement_transaction_id: UUID = Field(foreign_key="transactions.id")
    amount: Decimal = Field(sa_type=Amount())
    created: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))


class ContactRequest(SQLModel, table=True):
    """An idempotency key a client sent with a money-moving request, and the entry it produced: sending the same key
    again returns that entry instead of doing it twice."""

    __tablename__ = "contact_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_contact_requests_user_key"),
        Index("ix_contact_requests_transaction", "transaction_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    key: str = Field(max_length=100)
    transaction_id: UUID = Field(foreign_key="transactions.id")
    created: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))


class SharedExpense(TimestampMixin, table=True):
    """An expense split with contacts. A draft is only the plan; confirming it records one ledger entry (`transaction_id`)
    and the obligations it leaves. Cancelling removes it all."""

    __tablename__ = "shared_expenses"
    __table_args__ = (
        UniqueConstraint("transaction_id", name="uq_shared_expenses_transaction"),
        CheckConstraint("total_amount > 0", name="ck_shared_expenses_total"),
        CheckConstraint("split_method IN ('equal', 'exact', 'percentage', 'shares')", name="ck_shared_expenses_method"),
        CheckConstraint("status IN ('draft', 'confirmed')", name="ck_shared_expenses_status"),
        CheckConstraint(
            "(status = 'confirmed') = (transaction_id IS NOT NULL)", name="ck_shared_expenses_confirmed_has_entry"
        ),
        Index("ix_shared_expenses_user", "user_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    transaction_id: UUID | None = Field(default=None, foreign_key="transactions.id")
    description: str = Field(max_length=40)
    date: date_type
    total_amount: Decimal = Field(sa_type=Amount())
    # What the owner's own share is spent under (none means Uncategorised).
    category_id: UUID | None = Field(default=None, foreign_key="budget_categories.id")
    split_method: str = Field(max_length=10)
    status: str = Field(default="draft", max_length=9)


class ExpenseShare(SQLModel, table=True):
    """What one participant is responsible for: the owner (`is_self`) or a contact."""

    __tablename__ = "expense_shares"
    __table_args__ = (
        CheckConstraint(
            "(is_self AND contact_id IS NULL) OR (NOT is_self AND contact_id IS NOT NULL)",
            name="ck_expense_shares_participant",
        ),
        CheckConstraint("share_amount >= 0", name="ck_expense_shares_amount"),
        UniqueConstraint("shared_expense_id", "contact_id", name="uq_expense_shares_contact"),
        Index(
            "uq_expense_shares_self",
            "shared_expense_id",
            unique=True,
            sqlite_where=text("is_self"),
            postgresql_where=text("is_self"),
        ),
        Index("ix_expense_shares_user", "user_id"),
        Index("ix_expense_shares_expense", "shared_expense_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    shared_expense_id: UUID = Field(foreign_key="shared_expenses.id")
    contact_id: UUID | None = Field(default=None, foreign_key="contacts.id")
    is_self: bool = Field(default=False)
    share_amount: Decimal = Field(sa_type=Amount())
    # The percentage, the weight or the amount the share was worked out from (none for an equal split).
    share_value: Decimal | None = Field(default=None, sa_type=Amount())
    created: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))


class ExpenseContribution(SQLModel, table=True):
    """What one participant paid towards the expense. The owner's payments name the account they left (one row each); a
    contact's payment is one row and moves nothing in the owner's accounts."""

    __tablename__ = "expense_contributions"
    __table_args__ = (
        CheckConstraint(
            "(is_self AND contact_id IS NULL AND account_id IS NOT NULL) "
            "OR (NOT is_self AND contact_id IS NOT NULL AND account_id IS NULL)",
            name="ck_expense_contributions_participant",
        ),
        CheckConstraint("amount > 0", name="ck_expense_contributions_amount"),
        UniqueConstraint("shared_expense_id", "contact_id", name="uq_expense_contributions_contact"),
        UniqueConstraint("shared_expense_id", "account_id", name="uq_expense_contributions_account"),
        Index("ix_expense_contributions_user", "user_id"),
        Index("ix_expense_contributions_expense", "shared_expense_id"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="auth.users.id")
    shared_expense_id: UUID = Field(foreign_key="shared_expenses.id")
    contact_id: UUID | None = Field(default=None, foreign_key="contacts.id")
    is_self: bool = Field(default=False)
    account_id: UUID | None = Field(default=None, foreign_key="accounts.id")
    amount: Decimal = Field(sa_type=Amount())
    created: datetime = Field(default_factory=utc_now, sa_type=DateTime(timezone=True))
