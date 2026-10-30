"""Categories stand alone: the Income and Expenses accounts that only mirrored them are gone

Revision ID: f5b7d9e1a3c4
Revises: e4a6c8d0f2b3
Create Date: 2026-10-30 12:00:00.000000

Until now every category had a books account with the same id (`accounts.category_id = accounts.aid`), so spending was
posted to `Expenses › Food › Groceries`. The books are pure now: the ledger's other side of an expense or an income
is the root `Expenses` or `Income` account itself, and the line says what it was for (`postings.category_id`).

For every such mirror account: its postings move to the root (their category stays, and is set from the account first
when a line had none), recurring rules that named it name the root and carry the category, and the account is deleted
(deepest first). A real books account made by the person (one that feeds a category without being its mirror) stays,
under the root when its parent was a mirror. `accounts.payment_category_id` now points at the category table.

Before finishing, the migration compares what each category took in each month, every other account's balance and the
number of entries with an account on both sides, before and after; any difference refuses it, changing nothing.
The downgrade makes the mirror accounts again from the categories.
"""

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


def _figures(conn, skip: set) -> tuple[dict, dict, int]:
    """(what each category took per month, the balance of every other account, entries with an account on both sides)."""
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
    both = conn.execute(
        sa.text(
            'SELECT count(*) FROM (SELECT "transaction", account FROM postings GROUP BY "transaction", account '
            "HAVING count(DISTINCT side) > 1) x"
        )
    ).scalar()
    return (
        {k: v for k, v in by_category.items() if v},
        {k: v for k, v in balances.items() if v},
        both or 0,
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
    root_of = {}
    for aid, user, _parent, kind in mirrors:
        root = roots.get((_same(user), ROOTS.get(kind, "")))
        if root is None:
            raise RuntimeError("a category has no Income or Expenses root to move to; nothing was changed.")
        root_of[aid] = root
    before = _figures(conn, mirror_ids | set(roots.values()))

    for aid in mirror_ids:
        conn.execute(
            sa.text("UPDATE postings SET category_id = :c WHERE account = :a AND category_id IS NULL"),
            {"c": aid, "a": aid},
        )
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

    # A real books account that sat inside a mirror account moves up to the root (its name must stay free there).
    inside = conn.execute(sa.text('SELECT aid, "user", parent_id, name FROM accounts')).all()
    taken = {(u, p, n.casefold()) for _a, u, p, n in inside}
    for aid, user, parent, name in inside:
        if aid in mirror_ids or parent not in mirror_ids:
            continue
        root = root_of[parent]
        new = name
        while (user, root, new.casefold()) in taken:
            new = f"{new} (moved)"
        taken.add((user, root, new.casefold()))
        conn.execute(
            sa.text("UPDATE accounts SET parent_id = :r, name = :n WHERE aid = :a"), {"r": root, "n": new, "a": aid}
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

    after = _figures(conn, mirror_ids | set(roots.values()))
    if after != before:
        raise RuntimeError("the amounts per category or the balances changed; nothing was changed.")


def downgrade() -> None:
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
