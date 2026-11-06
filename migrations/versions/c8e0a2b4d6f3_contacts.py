"""Contacts: people the owner lends to, borrows from and shares expenses with

Revision ID: c8e0a2b4d6f3
Revises: b7d9f1a3c5e2
Create Date: 2026-11-06 10:00:00.000000

`contacts` holds the people; `contact_accounts` ties each to two ledger accounts, "Due from X" (an asset) and
"Due to X" (a liability). Nothing existing changes. Downgrading drops both tables (the two accounts of each contact
stay as ordinary accounts).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e0a2b4d6f3"
down_revision: str | Sequence[str] | None = "b7d9f1a3c5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_contacts_user_id"), "contacts", ["user_id"], unique=False)
    op.create_table(
        "contact_accounts",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.CheckConstraint("role IN ('receivable', 'payable')", name="ck_contact_accounts_role"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contact_id", "role", name="uq_contact_accounts_contact_role"),
        sa.UniqueConstraint("account_id", name="uq_contact_accounts_account"),
    )
    op.create_index("ix_contact_accounts_user", "contact_accounts", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_contact_accounts_user", table_name="contact_accounts")
    op.drop_table("contact_accounts")
    op.drop_index(op.f("ix_contacts_user_id"), table_name="contacts")
    op.drop_table("contacts")
