"""budget targets

Revision ID: c7e9a1b3d458
Revises: b5d7f9a1c346
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e9a1b3d458'
down_revision: Union[str, Sequence[str], None] = 'b5d7f9a1c346'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.aid"]),
        sa.PrimaryKeyConstraint("tgid"),
    )
    op.create_index(op.f("ix_budget_targets_user"), "budget_targets", ["user"], unique=False)
    op.create_index("uq_budget_targets", "budget_targets", ["user", "account_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_budget_targets", table_name="budget_targets")
    op.drop_index(op.f("ix_budget_targets_user"), table_name="budget_targets")
    op.drop_table("budget_targets")
