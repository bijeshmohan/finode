"""remove account type

Revision ID: 7aecda0dcc15
Revises: 6aecda0dcc15
Create Date: 2026-06-27 11:34:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '7aecda0dcc15'
down_revision: Union[str, Sequence[str], None] = '6aecda0dcc15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_index('ix_accounts_type')
        batch_op.drop_column('type')
        batch_op.create_index(
            'uq_accounts_user_root_name',
            ['user', 'name'],
            unique=True,
            sqlite_where=sa.text('parent_id IS NULL'),
            postgresql_where=sa.text('parent_id IS NULL'),
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_index('uq_accounts_user_root_name')
        batch_op.add_column(sa.Column('type', sa.VARCHAR(length=40), nullable=True))
        batch_op.create_index('ix_accounts_type', ['type'])
