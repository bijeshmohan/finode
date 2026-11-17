"""Remove the history of transactions and accounts

Revision ID: b7d9f1a3c5e2
Revises: a6c8e0b2d4f1
Create Date: 2026-11-05 15:00:00.000000

finode keeps no history of what happened to a transaction or an account any more: the three append-only tables
(`transaction_history`, `account_history`, `account_deletions`) are dropped, with everything the Undo button, the
Recently deleted pages, the change logs and the assistants' history tools read from them. The ledger itself is
untouched (`transactions.created_via` and `updated_via` stay). Downgrading brings back empty tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d9f1a3c5e2"
down_revision: str | Sequence[str] | None = "a6c8e0b2d4f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("transaction_history")
    op.drop_table("account_history")
    op.drop_table("account_deletions")


def downgrade() -> None:
    op.create_table(
        "account_deletions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_account_deletions_user_id"), "account_deletions", ["user_id"], unique=False)
    op.create_index("ix_account_deletions_user_account", "account_deletions", ["user_id", "account_id"])
    op.create_table(
        "account_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("via", sa.String(length=60), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "action IN ('created', 'updated', 'closed', 'reopened', 'restored', 'deleted')",
            name="ck_account_history_action",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_account_history_user_id"), "account_history", ["user_id"], unique=False)
    op.create_index("ix_account_history_user_account", "account_history", ["user_id", "account_id"])
    op.create_table(
        "transaction_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("via", sa.String(length=60), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint("action IN ('created', 'updated', 'deleted')", name="ck_transaction_history_action"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_transaction_history_user_id"), "transaction_history", ["user_id"], unique=False)
    op.create_index("ix_transaction_history_user_transaction", "transaction_history", ["user_id", "transaction_id"])
