"""Contacts, phase 2: what a contact owes and what they did (loans, borrowing, gifts)

Revision ID: d9f1b3c5e7a4
Revises: c8e0a2b4d6f3
Create Date: 2026-11-06 12:00:00.000000

`party_transactions` ties a ledger entry to a contact for their activity, `party_obligations` is one amount owed
either way (never changed: what is still owed is the amount less its settlements), `obligation_settlements` says which entry cleared how much of which
obligation, and `contact_requests` remembers an
idempotency key and the entry it made. Nothing existing changes; downgrading drops the three tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9f1b3c5e7a4"
down_revision: str | Sequence[str] | None = "c8e0a2b4d6f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "party_transactions",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.String(length=10), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('loan', 'borrowing', 'advance', 'gift', 'expense', 'settlement')",
            name="ck_party_transactions_purpose",
        ),
        sa.CheckConstraint("direction IN ('sent', 'received')", name="ck_party_transactions_direction"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contact_id", "transaction_id", name="uq_party_transactions_contact_transaction"),
    )
    op.create_index("ix_party_transactions_user", "party_transactions", ["user_id"])
    op.create_index("ix_party_transactions_transaction", "party_transactions", ["transaction_id"])
    op.create_table(
        "party_obligations",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("source_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=14), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("original_amount", sa.Numeric(24, 8), nullable=False),
        sa.CheckConstraint("original_amount > 0", name="ck_party_obligations_amount"),
        sa.CheckConstraint("direction IN ('receivable', 'payable')", name="ck_party_obligations_direction"),
        sa.CheckConstraint(
            "source_type IN ('shared_expense', 'loan', 'borrowing', 'advance')", name="ck_party_obligations_source"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["source_transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_party_obligations_user", "party_obligations", ["user_id"])
    op.create_index("ix_party_obligations_contact", "party_obligations", ["contact_id"])
    op.create_index("ix_party_obligations_source", "party_obligations", ["source_transaction_id"])
    op.create_table(
        "obligation_settlements",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("obligation_id", sa.Uuid(), nullable=False),
        sa.Column("settlement_transaction_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_obligation_settlements_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["obligation_id"], ["party_obligations.id"]),
        sa.ForeignKeyConstraint(["settlement_transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("obligation_id", "settlement_transaction_id", name="uq_obligation_settlements_pair"),
    )
    op.create_index("ix_obligation_settlements_user", "obligation_settlements", ["user_id"])
    op.create_index("ix_obligation_settlements_transaction", "obligation_settlements", ["settlement_transaction_id"])
    op.create_table(
        "contact_requests",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "key", name="uq_contact_requests_user_key"),
    )
    op.create_index("ix_contact_requests_transaction", "contact_requests", ["transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_contact_requests_transaction", table_name="contact_requests")
    op.drop_table("contact_requests")
    op.drop_index("ix_obligation_settlements_transaction", table_name="obligation_settlements")
    op.drop_index("ix_obligation_settlements_user", table_name="obligation_settlements")
    op.drop_table("obligation_settlements")
    for index in ("source", "contact", "user"):
        op.drop_index(f"ix_party_obligations_{index}", table_name="party_obligations")
    op.drop_table("party_obligations")
    op.drop_index("ix_party_transactions_transaction", table_name="party_transactions")
    op.drop_index("ix_party_transactions_user", table_name="party_transactions")
    op.drop_table("party_transactions")
