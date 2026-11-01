"""A card's statement day and payment due day

Revision ID: d8f0b2c4e6a9
Revises: c6e8a0b2d4f7
Create Date: 2026-11-01 15:00:00.000000

`accounts.statement_day` and `accounts.due_day` (1 to 31, or empty) let a liability account (a credit card, a loan) say
when its bank closes a bill and when it must be paid, so the bill can be worked out from the postings (see
services/cards.py). Both or neither: the checks keep the table honest whatever writes to it. Nothing existing changes.

The downgrade drops the columns and their checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8f0b2c4e6a9"
down_revision: str | Sequence[str] | None = "c6e8a0b2d4f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("statement_day", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("due_day", sa.Integer(), nullable=True))
        batch.create_check_constraint("ck_accounts_statement_day", "statement_day IS NULL OR statement_day BETWEEN 1 AND 31")
        batch.create_check_constraint("ck_accounts_due_day", "due_day IS NULL OR due_day BETWEEN 1 AND 31")
        batch.create_check_constraint("ck_accounts_bill_days_together", "(statement_day IS NULL) = (due_day IS NULL)")


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("ck_accounts_bill_days_together", type_="check")
        batch.drop_constraint("ck_accounts_due_day", type_="check")
        batch.drop_constraint("ck_accounts_statement_day", type_="check")
        batch.drop_column("due_day")
        batch.drop_column("statement_day")
