"""accounts can no longer be pinned: the flag goes

Revision ID: b6d8f0a2c4e7
Revises: a5c7e9b1d3f6
Create Date: 2026-10-17 12:00:00.000000

The Pinned block and the Pin button left the accounts page, so nothing reads or sets `accounts.pinned`.
Nothing else depended on it: the column only ever held "pinned or not".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6d8f0a2c4e7"
down_revision: str | Sequence[str] | None = "a5c7e9b1d3f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("pinned")


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
