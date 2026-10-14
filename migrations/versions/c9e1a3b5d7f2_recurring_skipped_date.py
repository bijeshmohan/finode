"""a recurring transaction remembers the occurrence that was skipped

Revision ID: c9e1a3b5d7f2
Revises: b8d0f2a4c6e1
Create Date: 2026-10-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9e1a3b5d7f2'
down_revision: Union[str, Sequence[str], None] = 'b8d0f2a4c6e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recurring_transactions") as batch:
        batch.add_column(sa.Column("skipped_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("recurring_transactions") as batch:
        batch.drop_column("skipped_date")
