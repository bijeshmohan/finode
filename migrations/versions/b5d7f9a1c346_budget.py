"""budget: allocations and the on_budget flag

Revision ID: b5d7f9a1c346
Revises: a3c5e7f9b124
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d7f9a1c346'
down_revision: Union[str, Sequence[str], None] = 'a3c5e7f9b124'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("on_budget", sa.Boolean(), nullable=False, server_default=sa.false()))

    # The money in asset accounts that hold a currency is budgeted unless the user says otherwise.
    connection = op.get_bind()
    accounts = sa.table(
        "accounts",
        sa.column("aid", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("parent_id", sa.Uuid()),
        sa.column("commodity_id", sa.Uuid()),
        sa.column("on_budget", sa.Boolean()),
    )
    commodities = sa.table("commodities", sa.column("cid", sa.Uuid()), sa.column("kind", sa.String()))
    currencies = {r[0] for r in connection.execute(sa.select(commodities.c.cid).where(commodities.c.kind == "currency"))}
    rows = connection.execute(sa.select(accounts.c.aid, accounts.c.name, accounts.c.parent_id, accounts.c.commodity_id)).all()
    by_id = {r.aid: r for r in rows}
    parents = {r.parent_id for r in rows if r.parent_id is not None}

    def root_name(row) -> str:
        seen = set()
        while row.parent_id is not None and row.aid not in seen:
            seen.add(row.aid)
            row = by_id.get(row.parent_id, row)
            if row.parent_id is None:
                break
        return row.name

    budgeted = [
        r.aid
        for r in rows
        if r.parent_id is not None and r.aid not in parents and r.commodity_id in currencies and root_name(r) == "Assets"
    ]
    if budgeted:
        connection.execute(accounts.update().where(accounts.c.aid.in_(budgeted)).values(on_budget=True))

    op.create_table(
        "budget_allocations",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.aid"]),
        sa.PrimaryKeyConstraint("bid"),
    )
    op.create_index(op.f("ix_budget_allocations_user"), "budget_allocations", ["user"], unique=False)
    op.create_index("uq_budget_allocations", "budget_allocations", ["user", "month", "account_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_budget_allocations", table_name="budget_allocations")
    op.drop_index(op.f("ix_budget_allocations_user"), table_name="budget_allocations")
    op.drop_table("budget_allocations")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("on_budget")
