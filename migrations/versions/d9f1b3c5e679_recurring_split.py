"""recurring transactions can be split across several accounts

Revision ID: d9f1b3c5e679
Revises: c7e9a1b3d458
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9f1b3c5e679'
down_revision: Union[str, Sequence[str], None] = 'c7e9a1b3d458'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recurring_transactions") as batch:
        batch.add_column(sa.Column("currency", sa.String(length=12), nullable=True))
        batch.alter_column("from_account", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("to_account", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("amount", existing_type=sa.Numeric(24, 8), nullable=True)

    op.create_table(
        "recurring_postings",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rpid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("rid", sa.Uuid(), nullable=False),
        sa.Column("account", sa.Uuid(), nullable=False),
        sa.Column("side", sa.String(length=6), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("side IN ('debit', 'credit')", name="ck_recurring_postings_side"),
        sa.CheckConstraint("amount > 0", name="ck_recurring_postings_amount"),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["rid"], ["recurring_transactions.rid"]),
        sa.ForeignKeyConstraint(["account"], ["accounts.aid"]),
        sa.PrimaryKeyConstraint("rpid"),
    )
    op.create_index(op.f("ix_recurring_postings_user"), "recurring_postings", ["user"], unique=False)
    op.create_index(op.f("ix_recurring_postings_rid"), "recurring_postings", ["rid"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_recurring_postings_rid"), table_name="recurring_postings")
    op.drop_index(op.f("ix_recurring_postings_user"), table_name="recurring_postings")
    op.drop_table("recurring_postings")
    # Split rules have no from, to or amount: they cannot be kept in the old shape.
    op.execute(
        "UPDATE transactions SET recurring_id = NULL WHERE recurring_id IN "
        "(SELECT rid FROM recurring_transactions WHERE from_account IS NULL)"
    )
    op.execute("DELETE FROM recurring_transactions WHERE from_account IS NULL")
    with op.batch_alter_table("recurring_transactions") as batch:
        batch.alter_column("amount", existing_type=sa.Numeric(24, 8), nullable=False)
        batch.alter_column("to_account", existing_type=sa.Uuid(), nullable=False)
        batch.alter_column("from_account", existing_type=sa.Uuid(), nullable=False)
        batch.drop_column("currency")
