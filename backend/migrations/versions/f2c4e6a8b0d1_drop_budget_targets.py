"""Remove budget targets

Revision ID: f2c4e6a8b0d1
Revises: e7b9d1f3a5c8
Create Date: 2026-10-24 18:00:00.000000

Budget targets (monthly, weekly, refill, by-date and yearly wishes per category, with "Assign what is needed" and the
week-by-week view) were taken out. Nothing else refers to the table; the plan (`budget_allocations`) and goals are
untouched. Downgrading brings back an empty table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2c4e6a8b0d1"
down_revision: str | Sequence[str] | None = "e7b9d1f3a5c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_budget_targets", table_name="budget_targets")
    op.drop_index(op.f("ix_budget_targets_user"), table_name="budget_targets")
    op.drop_table("budget_targets")


def downgrade() -> None:
    op.create_table(
        "budget_targets",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tgid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("weekday", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.aid"]),
        sa.PrimaryKeyConstraint("tgid"),
    )
    op.create_index(op.f("ix_budget_targets_user"), "budget_targets", ["user"], unique=False)
    op.create_index("uq_budget_targets", "budget_targets", ["user", "account_id"], unique=True)
