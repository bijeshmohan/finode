"""an advanced-features switch on the profile

Revision ID: e2a4c6e8f1b3
Revises: d1f3b5c7e9a4
Create Date: 2026-10-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a4c6e8f1b3"
down_revision: str | Sequence[str] | None = "d1f3b5c7e9a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("advanced", sa.Boolean(), nullable=False, server_default=sa.false()))
    # People who already have a profile keep seeing everything; the switch is off only for new people.
    op.execute(sa.text("UPDATE profiles SET advanced = :yes").bindparams(yes=True))


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("advanced")
