"""recurring transactions

Revision ID: f1a3c5e7b892
Revises: e8d0f2a4b569
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a3c5e7b892'
down_revision: Union[str, Sequence[str], None] = 'e8d0f2a4b569'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recurring_transactions",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("from_account", sa.Uuid(), nullable=False),
        sa.Column("to_account", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("received_amount", sa.Numeric(24, 8), nullable=True),
        sa.Column("payee", sa.String(length=40), nullable=True),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("frequency", sa.String(length=10), nullable=False),
        sa.Column("every", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("next_date", sa.Date(), nullable=False),
        sa.Column("last_date", sa.Date(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.CheckConstraint("frequency IN ('daily', 'weekly', 'monthly', 'yearly')", name="ck_recurring_frequency"),
        sa.CheckConstraint("every >= 1", name="ck_recurring_every"),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["from_account"], ["accounts.aid"]),
        sa.ForeignKeyConstraint(["to_account"], ["accounts.aid"]),
        sa.PrimaryKeyConstraint("rid"),
    )
    op.create_index(op.f("ix_recurring_transactions_user"), "recurring_transactions", ["user"], unique=False)
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("recurring_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("recurring_date", sa.Date(), nullable=True))
        batch.create_foreign_key("fk_transactions_recurring", "recurring_transactions", ["recurring_id"], ["rid"])
        batch.create_index(op.f("ix_transactions_recurring_id"), ["recurring_id"], unique=False)
        batch.create_index("uq_transactions_recurring", ["recurring_id", "recurring_date"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_index("uq_transactions_recurring")
        batch.drop_index(op.f("ix_transactions_recurring_id"))
        batch.drop_constraint("fk_transactions_recurring", type_="foreignkey")
        batch.drop_column("recurring_date")
        batch.drop_column("recurring_id")
    op.drop_index(op.f("ix_recurring_transactions_user"), table_name="recurring_transactions")
    op.drop_table("recurring_transactions")
