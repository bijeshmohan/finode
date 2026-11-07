"""Contacts, phase 3: expenses shared with contacts

Revision ID: e0a2c4d6f8b5
Revises: d9f1b3c5e7a4
Create Date: 2026-11-06 14:00:00.000000

`shared_expenses` is the plan of an expense split with contacts (a draft) or the record of one that was confirmed (it
then names its ledger entry), `expense_shares` what each participant is responsible for and `expense_contributions`
what each paid. Nothing existing changes; downgrading drops the three tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e0a2c4d6f8b5"
down_revision: str | Sequence[str] | None = "d9f1b3c5e7a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shared_expenses",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.String(length=40), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("total_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("split_method", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=9), nullable=False),
        sa.CheckConstraint("total_amount > 0", name="ck_shared_expenses_total"),
        sa.CheckConstraint(
            "split_method IN ('equal', 'exact', 'percentage', 'shares')", name="ck_shared_expenses_method"
        ),
        sa.CheckConstraint("status IN ('draft', 'confirmed')", name="ck_shared_expenses_status"),
        sa.CheckConstraint(
            "(status = 'confirmed') = (transaction_id IS NOT NULL)", name="ck_shared_expenses_confirmed_has_entry"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["budget_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_id", name="uq_shared_expenses_transaction"),
    )
    op.create_index("ix_shared_expenses_user", "shared_expenses", ["user_id"])
    op.create_table(
        "expense_shares",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("shared_expense_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("is_self", sa.Boolean(), nullable=False),
        sa.Column("share_amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("share_value", sa.Numeric(24, 8), nullable=True),
        sa.CheckConstraint(
            "(is_self AND contact_id IS NULL) OR (NOT is_self AND contact_id IS NOT NULL)",
            name="ck_expense_shares_participant",
        ),
        sa.CheckConstraint("share_amount >= 0", name="ck_expense_shares_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["shared_expense_id"], ["shared_expenses.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shared_expense_id", "contact_id", name="uq_expense_shares_contact"),
    )
    op.create_index(
        "uq_expense_shares_self",
        "expense_shares",
        ["shared_expense_id"],
        unique=True,
        sqlite_where=sa.text("is_self"),
        postgresql_where=sa.text("is_self"),
    )
    op.create_index("ix_expense_shares_user", "expense_shares", ["user_id"])
    op.create_index("ix_expense_shares_expense", "expense_shares", ["shared_expense_id"])
    op.create_table(
        "expense_contributions",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("shared_expense_id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("is_self", sa.Boolean(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=True),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.CheckConstraint(
            "(is_self AND contact_id IS NULL AND account_id IS NOT NULL) "
            "OR (NOT is_self AND contact_id IS NOT NULL AND account_id IS NULL)",
            name="ck_expense_contributions_participant",
        ),
        sa.CheckConstraint("amount > 0", name="ck_expense_contributions_amount"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["shared_expense_id"], ["shared_expenses.id"]),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shared_expense_id", "contact_id", name="uq_expense_contributions_contact"),
        sa.UniqueConstraint("shared_expense_id", "account_id", name="uq_expense_contributions_account"),
    )
    op.create_index("ix_expense_contributions_user", "expense_contributions", ["user_id"])
    op.create_index("ix_expense_contributions_expense", "expense_contributions", ["shared_expense_id"])


def downgrade() -> None:
    op.drop_index("ix_expense_contributions_expense", table_name="expense_contributions")
    op.drop_index("ix_expense_contributions_user", table_name="expense_contributions")
    op.drop_table("expense_contributions")
    op.drop_index("ix_expense_shares_expense", table_name="expense_shares")
    op.drop_index("ix_expense_shares_user", table_name="expense_shares")
    op.drop_index("uq_expense_shares_self", table_name="expense_shares")
    op.drop_table("expense_shares")
    op.drop_index("ix_shared_expenses_user", table_name="shared_expenses")
    op.drop_table("shared_expenses")
