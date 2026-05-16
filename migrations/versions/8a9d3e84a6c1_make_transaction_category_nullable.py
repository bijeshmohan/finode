"""make transaction category nullable

Revision ID: 8a9d3e84a6c1
Revises: e8abc44de1c4
Create Date: 2026-05-17 11:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8a9d3e84a6c1"
down_revision: Union[str, Sequence[str], None] = "e8abc44de1c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.alter_column(
            "category",
            existing_type=sa.Uuid(),
            nullable=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("transactions") as batch_op:
        batch_op.alter_column(
            "category",
            existing_type=sa.Uuid(),
            nullable=False,
        )
