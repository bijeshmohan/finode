"""every category has an icon

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-11-23 16:00:00.000000

`budget_categories.icon` names one of the icons in finode/category_icons.py. Existing categories get the generic `tag`
(the person picks theirs later); the built-in Uncategorised gets its own mark, `circle-dashed`. There is no CHECK on the
name: the set grows, and the services check it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2d4f6a8c0e1"
down_revision: str | Sequence[str] | None = "a1c3e5f7b9d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("budget_categories") as batch:
        batch.add_column(sa.Column("icon", sa.String(length=40), nullable=False, server_default="tag"))
    op.execute("UPDATE budget_categories SET icon = 'circle-dashed' WHERE system_key IS NOT NULL")
    with op.batch_alter_table("budget_categories") as batch:
        batch.alter_column("icon", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("budget_categories") as batch:
        batch.drop_column("icon")
