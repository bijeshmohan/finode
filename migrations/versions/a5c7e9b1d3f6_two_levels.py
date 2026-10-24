"""accounts are two levels deep at most: the depth limits on the profile go

Revision ID: a5c7e9b1d3f6
Revises: f4b6d8a0c2e5
Create Date: 2026-10-17 00:00:00.000000

Every top-level account allows a category and a sub-category (Expenses > Food > Groceries) and nothing
deeper, for everybody, so the per-person limits are dropped. The migration refuses (changing nothing) when
somebody still has an account deeper than that: flatten it first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5c7e9b1d3f6"
down_revision: str | Sequence[str] | None = "f4b6d8a0c2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("assets", "liabilities", "equity", "income", "expenses")
MAX_DEPTH = 2


def upgrade() -> None:
    connection = op.get_bind()
    parents = {
        str(aid): str(parent) if parent else None
        for aid, parent in connection.execute(sa.text("SELECT aid, parent_id FROM accounts"))
    }
    names = {str(aid): name for aid, name in connection.execute(sa.text("SELECT aid, name FROM accounts"))}

    def depth(aid: str) -> int:
        levels, seen = 0, {aid}
        while parents.get(aid) and parents[aid] in parents:
            aid = parents[aid]
            if aid in seen:
                break
            seen.add(aid)
            levels += 1
        return levels

    too_deep = sorted(names[aid] for aid in parents if depth(aid) > MAX_DEPTH)
    if too_deep:
        raise RuntimeError(
            f"{len(too_deep)} account(s) are more than two levels deep ({', '.join(too_deep[:5])}): "
            "move them up before migrating"
        )
    with op.batch_alter_table("profiles") as batch:
        batch.drop_constraint("ck_profiles_max_depth_non_negative", type_="check")
        for name in COLUMNS:
            batch.drop_column(f"max_depth_{name}")


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(f"max_depth_{name}", sa.Integer(), nullable=False, server_default="0"))
        batch.create_check_constraint(
            "ck_profiles_max_depth_non_negative",
            "max_depth_assets >= 0 AND max_depth_liabilities >= 0 AND max_depth_equity >= 0 "
            "AND max_depth_income >= 0 AND max_depth_expenses >= 0",
        )
