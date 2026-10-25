"""An entry can say where it came from outside finode

Revision ID: c1e3a5b7d9f0
Revises: b2d4f6a8c0e3
Create Date: 2026-10-25 12:00:00.000000

`transactions.source` (a short kind such as "gmail" or "upi"), `external_id` (the reference that source gave the
entry) and `source_url` (a link back). A person's `(source, external_id)` pair is unique, so an assistant that records
the same bank message twice finds the entry instead of making a copy. Nothing else reads them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1e3a5b7d9f0"
down_revision: str | Sequence[str] | None = "b2d4f6a8c0e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("transactions") as batch:
        batch.add_column(sa.Column("source", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("external_id", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("source_url", sa.String(length=500), nullable=True))
    op.create_index(
        "uq_transactions_reference",
        "transactions",
        ["user", "source", "external_id"],
        unique=True,
        sqlite_where=sa.text("external_id IS NOT NULL"),
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_transactions_reference", table_name="transactions")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_column("source_url")
        batch.drop_column("external_id")
        batch.drop_column("source")
