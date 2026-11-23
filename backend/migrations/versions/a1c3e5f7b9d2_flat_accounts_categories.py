"""accounts straight under their root with a type column; categories without parents

Revision ID: a1c3e5f7b9d2
Revises: f9b1d3e5a7c0
Create Date: 2026-11-23 12:00:00.000000

Each account under one of the four types' own accounts (Bank Account, Cash, Credit Card, Prepaid Wallet) moves straight
under its root and keeps the type in `accounts.type`; the type accounts and `accounts.system_key` go, and so does
`budget_categories.parent_id`. It refuses, changing nothing, while an account under Assets or Liabilities has no type
(a person's "Due from"/"Due to" aside), anything sits inside an account, two accounts would share a name under one root,
or a category still has a parent: those are for the person to fix by hand. The migration never picks a type. The
downgrade rebuilds the type accounts from the column; categories come back flat.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "a1c3e5f7b9d2"
down_revision: str | Sequence[str] | None = "f9b1d3e5a7c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = {
    "assets.bank": ("Bank Account", "Assets"),
    "assets.cash": ("Cash", "Assets"),
    "liabilities.cards": ("Credit Card", "Liabilities"),
    "assets.wallet": ("Prepaid Wallet", "Assets"),
}
HOLDING = ("Assets", "Liabilities")
CHECK = "type IS NULL OR type IN ('assets.bank', 'assets.cash', 'liabilities.cards', 'assets.wallet')"


def _refusals(connection: sa.Connection) -> list[str]:
    rows = connection.execute(sa.text("SELECT id, user_id, name, parent_id, system_key FROM accounts")).all()
    by_id = {r.id: r for r in rows}
    people = set(connection.execute(sa.text("SELECT account_id FROM contact_accounts")).scalars())

    def path(row: sa.Row) -> str:
        names, seen = [row.name], {row.id}
        while row.parent_id is not None and row.parent_id in by_id and row.parent_id not in seen:
            row = by_id[row.parent_id]
            seen.add(row.id)
            names.append(row.name)
        return ":".join(reversed(names))

    roots = {r.id for r in rows if r.parent_id is None}
    holding = {r.id: r.name for r in rows if r.parent_id is None and r.name in HOLDING}
    types = {r.id for r in rows if r.parent_id in holding and r.system_key in TYPES}
    problems: list[str] = []
    untyped = sorted(path(r) for r in rows if r.parent_id in holding and r.id not in types and r.id not in people)
    if untyped:
        problems.append(f"give these accounts a type first: {', '.join(untyped)}")
    deeper = sorted(path(r) for r in rows if r.parent_id is not None and r.parent_id not in roots | types)
    if deeper:
        problems.append(f"an account holds no accounts: {', '.join(deeper)}")
    taken: dict[tuple[object, object, str], str] = {}
    for r in rows:
        under = (
            r.parent_id if r.parent_id in holding else by_id[r.parent_id].parent_id if r.parent_id in types else None
        )
        if under is None or r.id in types:
            continue
        key = (r.user_id, under, r.name.casefold())
        if key in taken:
            problems.append(f"{taken[key]} under {holding[under]} twice: rename one first")
        taken[key] = r.name
    held = connection.execute(
        sa.text(
            "SELECT count(*) FROM postings WHERE account_id IN (SELECT id FROM accounts WHERE system_key IS NOT NULL)"
        )
    ).scalar()
    if held:
        problems.append("a type's own account holds entries: move them to an account of that type first")
    nested = sorted(
        connection.execute(sa.text("SELECT name FROM budget_categories WHERE parent_id IS NOT NULL")).scalars()
    )
    if nested:
        problems.append(f"flatten categories first: {', '.join(nested)}")
    return problems


def upgrade() -> None:
    connection = op.get_bind()
    problems = _refusals(connection)
    if problems:
        raise RuntimeError("; ".join(problems))
    before = connection.execute(sa.text("SELECT count(*) FROM accounts WHERE system_key IS NULL")).scalar()
    op.add_column("accounts", sa.Column("type", sa.String(length=20), nullable=True))
    nodes = connection.execute(
        sa.text(
            "SELECT t.id, t.parent_id, t.system_key FROM accounts t JOIN accounts root ON root.id = t.parent_id "
            "WHERE root.parent_id IS NULL AND t.system_key IN :keys"
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(TYPES)},
    ).all()
    for node in nodes:
        connection.execute(
            sa.text("UPDATE accounts SET type = :k, parent_id = :root WHERE parent_id = :node"),
            {"k": node.system_key, "root": node.parent_id, "node": node.id},
        )
    connection.execute(sa.text("DELETE FROM accounts WHERE system_key IS NOT NULL"))
    after = connection.execute(sa.text("SELECT count(*) FROM accounts")).scalar()
    if after != before:
        raise RuntimeError(f"accounts were lost: {before} before, {after} after")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_index("uq_accounts_user_system_key")
        batch.drop_column("system_key")
        batch.create_check_constraint("ck_accounts_type", CHECK)
    with op.batch_alter_table("budget_categories") as batch:
        batch.drop_column("parent_id")


def downgrade() -> None:
    connection = op.get_bind()
    with op.batch_alter_table("budget_categories") as batch:
        batch.add_column(sa.Column("parent_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_budget_categories_parent_id", "budget_categories", ["parent_id"], ["id"])
    op.add_column("accounts", sa.Column("system_key", sa.String(length=40), nullable=True))
    roots = connection.execute(
        sa.text("SELECT id, user_id, name FROM accounts WHERE parent_id IS NULL AND name IN :names").bindparams(
            sa.bindparam("names", expanding=True)
        ),
        {"names": list(HOLDING)},
    ).all()
    now = datetime.now(UTC)
    for root in roots:
        for key, (name, under) in TYPES.items():
            if root.name != under:
                continue
            node = uuid4()
            connection.execute(
                sa.text(
                    "INSERT INTO accounts (id, user_id, name, parent_id, system_key, bill_rounding, pinned, created, "
                    "updated) VALUES (:id, :u, :n, :p, :k, 'none', :no, :t, :t)"
                ).bindparams(sa.bindparam("id", type_=sa.Uuid()), sa.bindparam("t", type_=sa.DateTime(timezone=True))),
                {"id": node, "u": root.user_id, "n": name, "p": root.id, "k": key, "no": False, "t": now},
            )
            connection.execute(
                sa.text("UPDATE accounts SET parent_id = :node WHERE user_id = :u AND type = :k").bindparams(
                    sa.bindparam("node", type_=sa.Uuid())
                ),
                {"node": node, "u": root.user_id, "k": key},
            )
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("ck_accounts_type", type_="check")
        batch.drop_column("type")
        batch.create_index(
            "uq_accounts_user_system_key",
            ["user_id", "system_key"],
            unique=True,
            sqlite_where=sa.text("system_key IS NOT NULL"),
            postgresql_where=sa.text("system_key IS NOT NULL"),
        )
