"""accounts can be pinned again: a flag that lists the account in a Pinned row on the Accounts page

Revision ID: d7e9a1c3b5f8
Revises: c6d8f0a2b4e7
Create Date: 2026-11-10 18:00:00.000000

`accounts.pinned` (false for everything) is set from the account's own page. It changes no balance and no budget: it
only says where the Accounts page also lists the account. (An earlier version of the column was dropped by
`b6d8f0a2c4e7`; the old pins were not kept.)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e9a1c3b5f8"
down_revision: str | Sequence[str] | None = "c6d8f0a2b4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("pinned")
