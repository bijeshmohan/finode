"""A line's posting date and a card's bill rounding

Revision ID: e1a3c5b7d9f2
Revises: d8f0b2c4e6a9
Create Date: 2026-11-01 18:00:00.000000

`postings.posted_on` is the day an account posts a line when that is not the entry's own date (a card that bills a
purchase in a later statement); empty means the entry's date. `accounts.bill_rounding` is how the bank rounds a bill:
`none` (to the paisa), `nearest` or `up` (to a whole unit). Nothing existing changes: every line keeps no posting date
and every account keeps today's exact bill.

The downgrade drops both columns (the posting dates and rounding rules are lost).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a3c5b7d9f2"
down_revision: str | Sequence[str] | None = "d8f0b2c4e6a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("postings") as batch:
        batch.add_column(sa.Column("posted_on", sa.Date(), nullable=True))
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("bill_rounding", sa.String(length=8), nullable=False, server_default="none"))
        batch.create_check_constraint("ck_accounts_bill_rounding", "bill_rounding IN ('none', 'nearest', 'up')")


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("ck_accounts_bill_rounding", type_="check")
        batch.drop_column("bill_rounding")
    with op.batch_alter_table("postings") as batch:
        batch.drop_column("posted_on")
