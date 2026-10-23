"""accounts.system_key: the built-in groups under Assets and Liabilities

Revision ID: b9d1f3a5c7e2
Revises: a7c9e1b3d5f2
Create Date: 2026-10-21 18:00:00.000000

Additive and empty for everybody who already has accounts: the built-in groups (Bank Accounts, Cash, Investments,
Credit Cards, Loans) are made only for people who sign up after this change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9d1f3a5c7e2'
down_revision: Union[str, Sequence[str], None] = 'a7c9e1b3d5f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("system_key", sa.String(length=40), nullable=True))
    op.create_index(
        "uq_accounts_user_system_key",
        "accounts",
        ["user", "system_key"],
        unique=True,
        sqlite_where=sa.text("system_key IS NOT NULL"),
        postgresql_where=sa.text("system_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_accounts_user_system_key", table_name="accounts")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("system_key")
