"""rename_base_account_types

Revision ID: 64e7da0aed4b
Revises: 1c1a7d54333c
Create Date: 2026-06-07 17:07:55.919864

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '64e7da0aed4b'
down_revision: Union[str, Sequence[str], None] = '1c1a7d54333c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update existing account records to capitalized names
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE accounts SET type = CASE type "
            "WHEN 'asset' THEN 'Assets' "
            "WHEN 'liability' THEN 'Liabilities' "
            "WHEN 'equity' THEN 'Equity' "
            "WHEN 'income' THEN 'Income' "
            "WHEN 'expense' THEN 'Expenses' "
            "ELSE type END"
        )
    )

    # 2. Update the server default of accounts.type to 'Assets'
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.alter_column('type',
               existing_type=sa.VARCHAR(length=20),
               server_default='Assets',
               existing_nullable=False)


def downgrade() -> None:
    # 1. Update the server default back to 'asset'
    with op.batch_alter_table('accounts', schema=None) as batch_op:
        batch_op.alter_column('type',
               existing_type=sa.VARCHAR(length=20),
               server_default='asset',
               existing_nullable=False)

    # 2. Update account records back to lowercase names
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE accounts SET type = CASE type "
            "WHEN 'Assets' THEN 'asset' "
            "WHEN 'Liabilities' THEN 'liability' "
            "WHEN 'Equity' THEN 'equity' "
            "WHEN 'Income' THEN 'income' "
            "WHEN 'Expenses' THEN 'expense' "
            "ELSE type END"
        )
    )
