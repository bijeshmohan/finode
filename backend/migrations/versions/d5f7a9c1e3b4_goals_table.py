"""Goals get their own tables

Revision ID: d5f7a9c1e3b4
Revises: c4e6a8b0d2f4
Create Date: 2026-10-23 12:00:00.000000

A goal used to be an Expenses category with a "by a month" target and nothing inside it. It is now its own thing:
`goals` (name, amount, month) and `goal_allocations` (what was set aside, month by month). Every goal of the old kind
that nothing else refers to (no entry, recurring rule or payment link) moves across with its set-aside amounts and its
category is removed. One that has entries or is used elsewhere stays what it is: an ordinary category with a target.
Ready to assign does not change. The upgrade cannot be undone once goals exist (restore a backup instead).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5f7a9c1e3b4"
down_revision: str | Sequence[str] | None = "c4e6a8b0d2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("gid"),
    )
    op.create_index(op.f("ix_goals_user"), "goals", ["user"], unique=False)
    op.create_table(
        "goal_allocations",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gaid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.gid"]),
        sa.PrimaryKeyConstraint("gaid"),
    )
    op.create_index(op.f("ix_goal_allocations_user"), "goal_allocations", ["user"], unique=False)
    op.create_index(op.f("ix_goal_allocations_goal_id"), "goal_allocations", ["goal_id"], unique=False)
    op.create_index("uq_goal_allocations", "goal_allocations", ["user", "month", "goal_id"], unique=True)
    _move_old_goals(op.get_bind())


def _move_old_goals(conn) -> None:
    accounts = sa.table(
        "accounts",
        sa.column("aid", sa.Uuid()),
        sa.column("user", sa.Uuid()),
        sa.column("parent_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("payment_category_id", sa.Uuid()),
    )
    targets = sa.table(
        "budget_targets",
        sa.column("account_id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("amount", sa.Numeric(24, 8)),
        sa.column("target_date", sa.Date()),
    )
    allocations = sa.table(
        "budget_allocations",
        sa.column("account_id", sa.Uuid()),
        sa.column("month", sa.Date()),
        sa.column("amount", sa.Numeric(24, 8)),
    )
    postings = sa.table("postings", sa.column("account", sa.Uuid()))
    rules = sa.table("recurring_transactions", sa.column("from_account", sa.Uuid()), sa.column("to_account", sa.Uuid()))
    rule_postings = sa.table("recurring_postings", sa.column("account", sa.Uuid()))
    goals = sa.table(
        "goals",
        sa.column("created", sa.DateTime(timezone=True)),
        sa.column("updated", sa.DateTime(timezone=True)),
        sa.column("gid", sa.Uuid()),
        sa.column("user", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("amount", sa.Numeric(24, 8)),
        sa.column("target_date", sa.Date()),
    )
    goal_rows = sa.table(
        "goal_allocations",
        sa.column("created", sa.DateTime(timezone=True)),
        sa.column("updated", sa.DateTime(timezone=True)),
        sa.column("gaid", sa.Uuid()),
        sa.column("user", sa.Uuid()),
        sa.column("month", sa.Date()),
        sa.column("goal_id", sa.Uuid()),
        sa.column("amount", sa.Numeric(24, 8)),
    )

    rows = {
        r.aid: r
        for r in conn.execute(
            sa.select(
                accounts.c.aid, accounts.c.user, accounts.c.parent_id, accounts.c.name, accounts.c.payment_category_id
            )
        )
    }
    parents = {r.parent_id for r in rows.values() if r.parent_id is not None}
    used = {r.account for r in conn.execute(sa.select(postings.c.account))}
    used |= {r.account for r in conn.execute(sa.select(rule_postings.c.account))}
    for r in conn.execute(sa.select(rules.c.from_account, rules.c.to_account)):
        used |= {a for a in (r.from_account, r.to_account) if a is not None}
    used |= {r.payment_category_id for r in rows.values() if r.payment_category_id is not None}

    def expense(aid) -> bool:
        seen = set()
        while aid in rows and rows[aid].parent_id is not None and aid not in seen:
            seen.add(aid)
            aid = rows[aid].parent_id
        return aid in rows and rows[aid].name == "Expenses"

    now = datetime.now(UTC)
    for t in conn.execute(
        sa.select(targets.c.account_id, targets.c.amount, targets.c.target_date).where(targets.c.kind == "by_date")
    ).all():
        aid = t.account_id
        if (
            aid not in rows
            or aid in parents
            or aid in used
            or rows[aid].parent_id is None
            or not expense(aid)
            or t.target_date is None
        ):
            continue
        account, gid = rows[aid], uuid4()
        conn.execute(
            goals.insert().values(
                created=now,
                updated=now,
                gid=gid,
                user=account.user,
                name=account.name[:80],
                amount=t.amount,
                target_date=t.target_date,
            )
        )
        for a in conn.execute(
            sa.select(allocations.c.month, allocations.c.amount).where(allocations.c.account_id == aid)
        ).all():
            conn.execute(
                goal_rows.insert().values(
                    created=now,
                    updated=now,
                    gaid=uuid4(),
                    user=account.user,
                    month=a.month,
                    goal_id=gid,
                    amount=a.amount,
                )
            )
        conn.execute(allocations.delete().where(allocations.c.account_id == aid))
        conn.execute(targets.delete().where(targets.c.account_id == aid))
        conn.execute(accounts.delete().where(accounts.c.aid == aid))


def downgrade() -> None:
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT 1 FROM goals LIMIT 1")).first() is not None:
        raise RuntimeError("goals exist and have no place in the older schema: restore a backup instead of going back!")
    op.drop_index("uq_goal_allocations", table_name="goal_allocations")
    op.drop_index(op.f("ix_goal_allocations_goal_id"), table_name="goal_allocations")
    op.drop_index(op.f("ix_goal_allocations_user"), table_name="goal_allocations")
    op.drop_table("goal_allocations")
    op.drop_index(op.f("ix_goals_user"), table_name="goals")
    op.drop_table("goals")
