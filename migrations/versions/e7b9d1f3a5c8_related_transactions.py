"""An entry can be related to an earlier one

Revision ID: e7b9d1f3a5c8
Revises: d5f7a9c1e3b4
Create Date: 2026-10-24 12:00:00.000000

`transactions.related_id` points at another entry of the same person (a refund, a reversal, a cash-back…). It is only
a link: no amounts or accounts depend on it, and deleting the entry it points at clears it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7b9d1f3a5c8'
down_revision: Union[str, Sequence[str], None] = 'd5f7a9c1e3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("related_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_transactions_related_id", "transactions", ["related_id"], ["tid"])
        batch.create_index("ix_transactions_related_id", ["related_id"])


def downgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.drop_index("ix_transactions_related_id")
        batch.drop_constraint("fk_transactions_related_id", type_="foreignkey")
        batch.drop_column("related_id")
