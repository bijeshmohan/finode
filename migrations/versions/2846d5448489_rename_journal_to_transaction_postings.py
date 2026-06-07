"""rename journal to transaction postings

Revision ID: 2846d5448489
Revises: 0002
Create Date: 2026-06-07 11:25:19.122418

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '2846d5448489'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1. Rename journal_entries to transactions
    op.rename_table('journal_entries', 'transactions')
    
    # 2. Drop index on transactions
    op.drop_index('ix_journal_entries_user', table_name='transactions')
    
    # 3. Rename columns on transactions
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('jid', new_column_name='tid')
        
    # 4. Create new index on transactions
    op.create_index('ix_transactions_user', 'transactions', ['user'], unique=False)

    # 5. Rename journal_lines to postings
    op.rename_table('journal_lines', 'postings')
    
    # 6. Drop indexes on postings
    op.drop_index('ix_journal_lines_account', table_name='postings')
    op.drop_index('ix_journal_lines_entry', table_name='postings')
    op.drop_index('ix_journal_lines_user', table_name='postings')
    
    # 7. Rename columns on postings
    with op.batch_alter_table('postings', schema=None) as batch_op:
        batch_op.alter_column('lid', new_column_name='pid')
        batch_op.alter_column('entry', new_column_name='transaction')
        
    # 8. Create new indexes on postings
    op.create_index('ix_postings_account', 'postings', ['account'], unique=False)
    op.create_index('ix_postings_transaction', 'postings', ['transaction'], unique=False)
    op.create_index('ix_postings_user', 'postings', ['user'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # 1. Rename postings to journal_lines
    op.rename_table('postings', 'journal_lines')
    
    # 2. Drop indexes on journal_lines
    op.drop_index('ix_postings_account', table_name='journal_lines')
    op.drop_index('ix_postings_transaction', table_name='journal_lines')
    op.drop_index('ix_postings_user', table_name='journal_lines')
    
    # 3. Rename columns on journal_lines
    with op.batch_alter_table('journal_lines', schema=None) as batch_op:
        batch_op.alter_column('pid', new_column_name='lid')
        batch_op.alter_column('transaction', new_column_name='entry')
        
    # 4. Create indexes on journal_lines
    op.create_index('ix_journal_lines_account', 'journal_lines', ['account'], unique=False)
    op.create_index('ix_journal_lines_entry', 'journal_lines', ['entry'], unique=False)
    op.create_index('ix_journal_lines_user', 'journal_lines', ['user'], unique=False)
        
    # 5. Rename transactions to journal_entries
    op.rename_table('transactions', 'journal_entries')
    
    # 6. Drop index on journal_entries
    op.drop_index('ix_transactions_user', table_name='journal_entries')
    
    # 7. Rename columns on journal_entries
    with op.batch_alter_table('journal_entries', schema=None) as batch_op:
        batch_op.alter_column('tid', new_column_name='jid')
        
    # 8. Create index on journal_entries
    op.create_index('ix_journal_entries_user', 'journal_entries', ['user'], unique=False)
