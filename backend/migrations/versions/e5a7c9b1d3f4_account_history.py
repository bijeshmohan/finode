"""An append-only history of what happened to each account

Revision ID: e5a7c9b1d3f4
Revises: d3f5b7c9e1a2
Create Date: 2026-10-25 16:00:00.000000

One row per creation, change, closing, reopening, restoring and deletion of an account or category, with who did it
and what it looked like afterwards. Nothing existing is touched; changes made before this have no history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5a7c9b1d3f4"
down_revision: str | Sequence[str] | None = "d3f5b7c9e1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_history",
        sa.Column("hid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("via", sa.String(length=60), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "action IN ('created', 'updated', 'closed', 'reopened', 'restored', 'deleted')",
            name="ck_account_history_action",
        ),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("hid"),
    )
    op.create_index(op.f("ix_account_history_user"), "account_history", ["user"], unique=False)
    op.create_index("ix_account_history_user_account", "account_history", ["user", "account_id"])


def downgrade() -> None:
    op.drop_index("ix_account_history_user_account", table_name="account_history")
    op.drop_index(op.f("ix_account_history_user"), table_name="account_history")
    op.drop_table("account_history")
