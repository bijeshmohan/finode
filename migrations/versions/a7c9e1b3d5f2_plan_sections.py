"""profiles.plan_build and plan_earn: which sections of the Plan the person uses

Revision ID: a7c9e1b3d5f2
Revises: d1e3f5a7b9c2
Create Date: 2026-10-21 12:00:00.000000

Additive. Build starts on for everybody; Earn starts on for the people who have the Advanced switch on, because until now that
is what showed it, so nothing disappears on deploy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c9e1b3d5f2'
down_revision: Union[str, Sequence[str], None] = 'd1e3f5a7b9c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("plan_build", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("plan_earn", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("UPDATE profiles SET plan_earn = advanced")


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("plan_earn")
        batch.drop_column("plan_build")
