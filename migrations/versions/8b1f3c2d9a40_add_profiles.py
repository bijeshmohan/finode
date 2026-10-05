"""add profiles

Revision ID: 8b1f3c2d9a40
Revises: 7aecda0dcc15
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '8b1f3c2d9a40'
down_revision: Union[str, Sequence[str], None] = '7aecda0dcc15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("first_name", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=True),
        sa.Column("last_name", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=True),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("user"),
    )


def downgrade() -> None:
    op.drop_table("profiles")
