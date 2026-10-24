"""Remove the period lock and the hand-set order of accounts

Revision ID: b2d4f6a8c0e3
Revises: a9b1c3d5e7f2
Create Date: 2026-10-25 09:00:00.000000

`profiles.locked_through` (the period lock) and `accounts.position` (Move up / Move down) were removed: nobody used
them. Accounts are listed alphabetically, the built-in groups first. Downgrading adds both columns back, empty
(no lock, alphabetical order).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d4f6a8c0e3"
down_revision: str | Sequence[str] | None = "a9b1c3d5e7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("locked_through")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("position")


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("position", sa.Integer(), nullable=True))
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("locked_through", sa.Date(), nullable=True))
