"""a record of the accounts and categories deleted for good, so they can be brought back

Revision ID: c8f0b2d4e6a1
Revises: b6d8f0a2c4e7
Create Date: 2026-10-17 18:00:00.000000

Only an unused account can be deleted (no entries, sub-accounts or rules), so its trace is small: the
account itself, the amounts planned for it, its target and which accounts budgeted their payments under it.
Existing deletions left no trace, so the table starts empty.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8f0b2d4e6a1'
down_revision: Union[str, Sequence[str], None] = 'b6d8f0a2c4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_deletions",
        sa.Column("did", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("did"),
    )
    op.create_index(op.f("ix_account_deletions_user"), "account_deletions", ["user"], unique=False)
    op.create_index("ix_account_deletions_user_account", "account_deletions", ["user", "account_id"])


def downgrade() -> None:
    op.drop_index("ix_account_deletions_user_account", table_name="account_deletions")
    op.drop_index(op.f("ix_account_deletions_user"), table_name="account_deletions")
    op.drop_table("account_deletions")
