"""Remove goals

Revision ID: a6c8e0b2d4f1
Revises: e1a3c5b7d9f2
Create Date: 2026-11-05 12:00:00.000000

The Save chip (savings goals with money set aside month by month) was taken out. Nothing else refers to the two tables;
the plan (`budget_allocations`) is untouched. What was set aside in a goal was never part of the categories' money, so
the goal's amount returns to Ready to assign by itself. Downgrading brings back empty tables.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6c8e0b2d4f1"
down_revision: str | Sequence[str] | None = "e1a3c5b7d9f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("goal_allocations")
    op.drop_table("goals")


def downgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goals_user_id"), "goals", ["user_id"], unique=False)
    op.create_table(
        "goal_allocations",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goal_allocations_user_id"), "goal_allocations", ["user_id"], unique=False)
    op.create_index(op.f("ix_goal_allocations_goal_id"), "goal_allocations", ["goal_id"], unique=False)
    op.create_index("uq_goal_allocations", "goal_allocations", ["user_id", "month", "goal_id"], unique=True)
