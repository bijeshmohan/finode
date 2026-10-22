"""Remove the Plan's Build and Earn sections

Revision ID: c4e6a8b0d2f4
Revises: b9d1f3a5c7e2
Create Date: 2026-10-22 12:00:00.000000

Drops accounts.saving and profiles.plan_build / plan_earn, and deletes the plan rows and targets that belonged to Build
lines (funds, deposits, loans) and Earn lines (expected income): the budget keeps only the rows of expense categories.
Only the plan is touched: no transaction, posting or account is. The upgrade cannot be undone for those rows (the
downgrade puts the columns back, switched off, and restore a backup to get the rows back).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e6a8b0d2f4'
down_revision: Union[str, Sequence[str], None] = 'b9d1f3a5c7e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    accounts = {row.aid: (row.parent_id, row.name) for row in conn.execute(sa.text("SELECT aid, parent_id, name FROM accounts"))}

    def expense(aid) -> bool:
        seen = set()
        while aid in accounts and accounts[aid][0] is not None and aid not in seen:
            seen.add(aid)
            aid = accounts[aid][0]
        return aid in accounts and accounts[aid][1] == "Expenses"

    for table in ("budget_allocations", "budget_targets"):
        stale = [row.account_id for row in conn.execute(sa.text(f"SELECT DISTINCT account_id FROM {table}")) if not expense(row.account_id)]
        for chunk in range(0, len(stale), 200):
            marks = ", ".join(f":a{i}" for i in range(len(stale[chunk:chunk + 200])))
            conn.execute(
                sa.text(f"DELETE FROM {table} WHERE account_id IN ({marks})"),
                {f"a{i}": aid for i, aid in enumerate(stale[chunk:chunk + 200])},
            )
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("saving")
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("plan_earn")
        batch.drop_column("plan_build")


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("plan_build", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("plan_earn", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("saving", sa.Boolean(), nullable=False, server_default=sa.false()))
