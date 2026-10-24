"""accounts.saving: an asset outside the budget that the person plans to save into

Revision ID: d1e3f5a7b9c2
Revises: c8f0b2d4e6a1
Create Date: 2026-10-20 12:00:00.000000

Additive: every existing account starts as not saving, so nothing changes until a person switches one on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e3f5a7b9c2"
down_revision: str | Sequence[str] | None = "c8f0b2d4e6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("saving", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("saving")
