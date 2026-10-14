"""accounts: the category payments into an account outside the budget are budgeted under

Revision ID: e1a3c5d7f891
Revises: d9f1b3c5e679
Create Date: 2026-10-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1a3c5d7f891'
down_revision: Union[str, Sequence[str], None] = 'd9f1b3c5e679'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("payment_category_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_accounts_payment_category", "accounts", ["payment_category_id"], ["aid"])


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("fk_accounts_payment_category", type_="foreignkey")
        batch.drop_column("payment_category_id")
