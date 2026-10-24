"""a period lock on the books

Revision ID: d1f3b5c7e9a4
Revises: c9e1a3b5d7f2
Create Date: 2026-10-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1f3b5c7e9a4"
down_revision: str | Sequence[str] | None = "c9e1a3b5d7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("locked_through", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("locked_through")
