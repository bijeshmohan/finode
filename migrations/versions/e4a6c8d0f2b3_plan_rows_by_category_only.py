"""Plan rows are kept against the category alone

Revision ID: e4a6c8d0f2b3
Revises: c7e9a1b3d5f8
Create Date: 2026-10-29 12:00:00.000000

`budget_allocations` had two keys while the budget moved over to categories: `account_id` (the Expenses account the row
was planned against) and `category_id`. The category is the only key now. Every row must already name its category (the
earlier migration set it; rows made since carry it); one that does not is refused, changing nothing. The downgrade brings
`account_id` back from the category's own account.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4a6c8d0f2b3"
down_revision: str | Sequence[str] | None = "c7e9a1b3d5f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE budget_allocations SET category_id = account_id WHERE category_id IS NULL AND account_id IN "
            "(SELECT bcid FROM budget_categories)"
        )
    )
    if conn.execute(sa.text("SELECT count(*) FROM budget_allocations WHERE category_id IS NULL")).scalar():
        raise RuntimeError("a plan row names no category; nothing was changed.")
    with op.batch_alter_table("budget_allocations") as batch:
        batch.drop_index("uq_budget_allocations")
        batch.drop_column("account_id")
        batch.alter_column("category_id", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("budget_allocations") as batch:
        batch.add_column(sa.Column("account_id", sa.Uuid(), nullable=True))
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE budget_allocations SET account_id = category_id WHERE category_id IN (SELECT aid FROM accounts)"
        )
    )
    if conn.execute(sa.text("SELECT count(*) FROM budget_allocations WHERE account_id IS NULL")).scalar():
        raise RuntimeError("a plan row's category has no account; cannot go back.")
    with op.batch_alter_table("budget_allocations") as batch:
        batch.alter_column("account_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key("fk_budget_allocations_account", "accounts", ["account_id"], ["aid"])
        batch.alter_column("category_id", existing_type=sa.Uuid(), nullable=True)
        batch.create_index("uq_budget_allocations", ["user", "month", "account_id"], unique=True)
