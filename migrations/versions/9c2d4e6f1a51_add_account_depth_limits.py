"""add account depth limits to profiles

Revision ID: 9c2d4e6f1a51
Revises: 8b1f3c2d9a40
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c2d4e6f1a51'
down_revision: Union[str, Sequence[str], None] = '8b1f3c2d9a40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = (
    "max_depth_assets",
    "max_depth_liabilities",
    "max_depth_equity",
    "max_depth_income",
    "max_depth_expenses",
)


def upgrade() -> None:
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        for name in COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Integer(), server_default="0", nullable=False))
        batch_op.create_check_constraint(
            "ck_profiles_max_depth_non_negative",
            " AND ".join(f"{name} >= 0" for name in COLUMNS),
        )


def downgrade() -> None:
    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.drop_constraint("ck_profiles_max_depth_non_negative", type_="check")
        for name in reversed(COLUMNS):
            batch_op.drop_column(name)
