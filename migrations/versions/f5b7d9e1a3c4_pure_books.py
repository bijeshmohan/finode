"""Categories stand alone: the Income and Expenses accounts that only mirrored them are gone

Revision ID: f5b7d9e1a3c4
Revises: e4a6c8d0f2b3
Create Date: 2026-10-30 12:00:00.000000

Until now every category had a books account with the same id (`accounts.category_id = accounts.aid`), so spending was
posted to `Expenses › Food › Groceries`. The books are pure now: the ledger's other side of an expense or an income
is the root `Expenses` or `Income` account itself, and the line says what it was for (`postings.category_id`).

For every such mirror account: its postings move to the root (their category stays, and is set from the account first
when a line had none), recurring rules that named it name the root and carry the category, and the account is deleted
(deepest first). `accounts.category_id` goes (nothing is left to point at), and `accounts.payment_category_id` now
points at the category table. An Income or Expenses account that is not a mirror (a "books account" the person made on
purpose) is not carried over: the migration refuses, changing nothing, so it is never lost silently.

Before finishing, the migration compares what each category took in each month, every other account's balance and the
number of entries with the same account and category on both sides, before and after; any difference refuses it.
The downgrade makes the mirror accounts again from the categories.
"""

import json
from collections import defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5b7d9e1a3c4"
down_revision: str | Sequence[str] | None = "e4a6c8d0f2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROOTS = {"spending": "Expenses", "earning": "Income"}


def _same(user) -> str:
    """A person's id as one string whether the database keeps it with dashes or without."""
    return str(user).replace("-", "")


def _root_ids(conn) -> dict[tuple, object]:
    rows = conn.execute(
        sa.text("SELECT aid, \"user\", name FROM accounts WHERE parent_id IS NULL AND name IN ('Expenses', 'Income')")
    ).all()
    return {(_same(r[1]), r[2]): r[0] for r in rows}


def _figures(conn, skip: set, keyed: set) -> tuple[dict, dict, int]:
    """(what each category took per month, the balance of every other account, entries with the same account (and,
    for the accounts in `keyed`, the same category) on both sides)."""
    by_category: dict = defaultdict(lambda: 0)
    for category, side, month, amount in conn.execute(
        sa.text(
            'SELECT p.category_id, p.side, t.date, p.amount FROM postings p JOIN transactions t ON t.tid = p."transaction" '
            "WHERE p.category_id IS NOT NULL"
        )
    ):
        sign = 1 if str(side).lower() == "debit" else -1
        by_category[(category, str(month)[:7])] += sign * amount
    balances: dict = defaultdict(lambda: 0)
    for account, side, amount in conn.execute(sa.text("SELECT account, side, amount FROM postings")):
        if account in skip:
            continue
        balances[account] += amount if str(side).lower() == "debit" else -amount
    sides: dict = defaultdict(set)
    for transaction, account, side, category in conn.execute(
        sa.text('SELECT "transaction", account, side, category_id FROM postings')
    ):
        sides[(transaction, account, category if account in keyed else None)].add(str(side).lower())
    both = sum(1 for v in sides.values() if len(v) > 1)
    return (
        {k: v for k, v in by_category.items() if v},
        {k: v for k, v in balances.items() if v},
        both,
    )


def upgrade() -> None:
    conn = op.get_bind()
    mirrors = conn.execute(
        sa.text(
            'SELECT a.aid, a."user", a.parent_id, c.kind FROM accounts a JOIN budget_categories c ON c.bcid = a.aid '
            "WHERE a.category_id = a.aid"
        )
    ).all()
    roots = _root_ids(conn)
    mirror_ids = {m[0] for m in mirrors}
    every = {r[0]: r for r in conn.execute(sa.text("SELECT aid, parent_id, name, category_id FROM accounts")).all()}

    def top(aid):
        while every[aid][1] is not None and every[aid][1] in every:
            aid = every[aid][1]
        return every[aid][2]

    for aid, parent, name, category in every.values():
        if parent is not None and top(aid) in ROOTS.values() and category != aid:
            raise RuntimeError(f"'{name}' is an Income or Expenses account of your own; nothing was changed.")
    root_of = {}
    for aid, user, _parent, kind in mirrors:
        root = roots.get((_same(user), ROOTS.get(kind, "")))
        if root is None:
            raise RuntimeError("a category has no Income or Expenses root to move to; nothing was changed.")
        root_of[aid] = root
    for aid in mirror_ids:  # a line on a mirror account is labelled with it, whatever it said before
        conn.execute(
            sa.text("UPDATE postings SET category_id = :c WHERE account = :a AND category_id IS NULL"),
            {"c": aid, "a": aid},
        )
    before = _figures(conn, mirror_ids | set(roots.values()), mirror_ids | set(roots.values()))

    for aid in mirror_ids:
        conn.execute(sa.text("UPDATE postings SET account = :r WHERE account = :a"), {"r": root_of[aid], "a": aid})
        for column in ("from_account", "to_account"):
            conn.execute(
                sa.text(
                    f"UPDATE recurring_transactions SET category_id = COALESCE(category_id, :c), {column} = :r "
                    f"WHERE {column} = :a"
                ),
                {"c": aid, "r": root_of[aid], "a": aid},
            )
        conn.execute(
            sa.text(
                "UPDATE recurring_postings SET category_id = COALESCE(category_id, :c), account = :r WHERE account = :a"
            ),
            {"c": aid, "r": root_of[aid], "a": aid},
        )

    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("fk_accounts_payment_category", type_="foreignkey")
    conn.execute(
        sa.text(
            "UPDATE accounts SET payment_category_id = NULL WHERE payment_category_id NOT IN (SELECT bcid FROM budget_categories)"
        )
    )
    with op.batch_alter_table("accounts") as batch:
        batch.create_foreign_key("fk_accounts_payment_category", "budget_categories", ["payment_category_id"], ["bcid"])

    # Delete the mirror accounts, the deepest first (a child names its parent).
    parent_of = {aid: parent for aid, _u, parent, _k in mirrors}

    def depth(aid) -> int:
        n = 0
        while parent_of.get(aid) in mirror_ids:
            aid = parent_of[aid]
            n += 1
        return n

    for aid in sorted(mirror_ids, key=depth, reverse=True):
        conn.execute(sa.text("UPDATE accounts SET category_id = NULL WHERE aid = :a"), {"a": aid})
        conn.execute(sa.text("DELETE FROM accounts WHERE aid = :a"), {"a": aid})

    # What was deleted for good under Expenses or Income was a category, not an account: it cannot come back as one.
    for did, snapshot in conn.execute(sa.text("SELECT did, snapshot FROM account_deletions")).all():
        data = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        if (data or {}).get("root") in ROOTS.values():
            conn.execute(sa.text("DELETE FROM account_deletions WHERE did = :d"), {"d": did})

    with op.batch_alter_table("accounts") as batch:
        batch.drop_index("ix_accounts_category_id")
        batch.drop_column("category_id")

    after = _figures(conn, mirror_ids | set(roots.values()), mirror_ids | set(roots.values()))
    if after != before:
        raise RuntimeError("the amounts per category or the balances changed; nothing was changed.")


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("category_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_accounts_category_id", "budget_categories", ["category_id"], ["bcid"])
        batch.create_index("ix_accounts_category_id", ["category_id"])
    conn = op.get_bind()
    roots = _root_ids(conn)
    cats = conn.execute(
        sa.text('SELECT bcid, "user", name, details, kind, parent_id, closed_on FROM budget_categories')
    ).all()
    by_id = {c[0]: c for c in cats}
    # Parents first: a group, then the categories in it.
    for bcid, user, name, details, kind, parent, closed_on in sorted(cats, key=lambda c: c[5] is not None):
        root = roots.get((_same(user), ROOTS[kind]))
        if root is None:
            continue
        conn.execute(
            sa.text(
                'INSERT INTO accounts (aid, "user", name, details, parent_id, category_id, closed_on, on_budget, created, updated) '
                "VALUES (:aid, :u, :n, :d, :p, :c, :x, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "aid": bcid,
                "u": user,
                "n": name,
                "d": details,
                "p": parent if parent in by_id else root,
                "c": bcid,
                "x": closed_on,
            },
        )
    for root in set(roots.values()):
        conn.execute(
            sa.text(
                "UPDATE postings SET account = category_id WHERE account = :r AND category_id IN (SELECT bcid FROM budget_categories)"
            ),
            {"r": root},
        )
        for column in ("from_account", "to_account"):
            conn.execute(
                sa.text(
                    f"UPDATE recurring_transactions SET {column} = category_id WHERE {column} = :r AND category_id IS NOT NULL"
                ),
                {"r": root},
            )
        conn.execute(
            sa.text(
                "UPDATE recurring_postings SET account = category_id WHERE account = :r AND category_id IS NOT NULL"
            ),
            {"r": root},
        )
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("fk_accounts_payment_category", type_="foreignkey")
        batch.create_foreign_key("fk_accounts_payment_category", "accounts", ["payment_category_id"], ["aid"])
