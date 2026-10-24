"""Remove the Advanced switch

Revision ID: a9b1c3d5e7f2
Revises: f2c4e6a8b0d1
Create Date: 2026-10-24 21:00:00.000000

`profiles.advanced` hid ordering and closing of accounts and the period lock until switched on. The switch was removed:
those features are always there. Downgrading adds the column back, switched off.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b1c3d5e7f2'
down_revision: Union[str, Sequence[str], None] = 'f2c4e6a8b0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("advanced")


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("advanced", sa.Boolean(), nullable=False, server_default=sa.false()))
