"""accounts can be pinned and ordered by hand

Revision ID: b8d0f2a4c6e1
Revises: a7c9e1b3d5f6
Create Date: 2026-10-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8d0f2a4c6e1'
down_revision: Union[str, Sequence[str], None] = 'a7c9e1b3d5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("position")
        batch.drop_column("pinned")
