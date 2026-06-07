"""rename_transaction_note_to_payee_and_details_to_comment

Revision ID: 1c1a7d54333c
Revises: 2846d5448489
Create Date: 2026-06-07 11:44:31.008484

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '1c1a7d54333c'
down_revision: Union[str, Sequence[str], None] = '2846d5448489'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('note', new_column_name='payee')
        batch_op.alter_column('details', new_column_name='comment')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('comment', new_column_name='details')
        batch_op.alter_column('payee', new_column_name='note')
