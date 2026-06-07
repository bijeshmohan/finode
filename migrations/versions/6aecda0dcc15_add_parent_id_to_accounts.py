"""add parent_id to accounts

Revision ID: 6aecda0dcc15
Revises: 64e7da0aed4b
Create Date: 2026-06-07 17:21:14.523366

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '6aecda0dcc15'
down_revision: Union[str, Sequence[str], None] = '64e7da0aed4b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('accounts', sa.Column('parent_id', sa.Uuid(), nullable=True))
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_accounts_parent_id', 'accounts', ['parent_id'], ['aid'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_accounts_parent_id', type_='foreignkey')
    op.drop_column('accounts', 'parent_id')

