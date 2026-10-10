"""accounts can be closed

Revision ID: f3b5d7e9a1c2
Revises: e1a3c5d7f891
Create Date: 2026-10-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b5d7e9a1c2'
down_revision: Union[str, Sequence[str], None] = 'e1a3c5d7f891'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("closed_on", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("closed_on")
