"""Recurring rules can carry tags

Revision ID: b3d5f7a9c1e2
Revises: a2c4e6f8b1d3
Create Date: 2026-10-26 18:00:00.000000

`recurring_transactions.tags`: the tags (each in its one form, lower case) that every entry the rule records gets.
Existing rules have none. The downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d5f7a9c1e2"
down_revision: str | Sequence[str] | None = "a2c4e6f8b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recurring_transactions",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    with op.batch_alter_table("recurring_transactions") as batch:
        batch.drop_column("tags")
