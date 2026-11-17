"""Budget categories, apart from the books' accounts

Revision ID: c7e9a1b3d5f8
Revises: b3d5f7a9c1e2
Create Date: 2026-10-28 12:00:00.000000

The budget used to plan against Expenses accounts, so a loan's EMI needed a made-up account to hang a plan on. Now a
category is its own thing (`budget_categories`: spending or earning, two levels), a label on the lines of an entry
(`postings.category_id`) and what the plan is kept against (`budget_allocations.category_id`). The Income and Expenses
accounts the books need point back at theirs (`accounts.category_id`).

Every Income and Expenses account below the roots becomes a category with the **same id**, name, parent, note and closed
day (so addresses and links keep working), every posting gets the category of its account, and a debit into a loan or
fund that has a payment category (in an entry that touches the budget) gets that category, which is how the budget
counted it before. Nothing the budget shows changes: before it finishes the migration works out each category's
spending by month with the old rule (accounts and payment categories) and with the new one (the categories on the lines)
and refuses, changing nothing, when they differ. Built-in Uncategorised categories are made later, with the roots.

`payment_category_id` and `budget_allocations.account_id` stay for now (a later migration drops them). The downgrade
removes the new columns and table; it is refused while a plan row exists that has no account.
"""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e9a1b3d5f8"
down_revision: str | Sequence[str] | None = "b3d5f7a9c1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROOT_KINDS = {"Expenses": "spending", "Income": "earning"}
ZERO = Decimal(0)

accounts = sa.table(
    "accounts",
    sa.column("aid", sa.Uuid()),
    sa.column("user", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("details", sa.String()),
    sa.column("parent_id", sa.Uuid()),
    sa.column("on_budget", sa.Boolean()),
    sa.column("closed_on", sa.Date()),
    sa.column("payment_category_id", sa.Uuid()),
    sa.column("category_id", sa.Uuid()),
)
categories = sa.table(
    "budget_categories",
    sa.column("created", sa.DateTime(timezone=True)),
    sa.column("updated", sa.DateTime(timezone=True)),
    sa.column("bcid", sa.Uuid()),
    sa.column("user", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("details", sa.String()),
    sa.column("kind", sa.String()),
    sa.column("parent_id", sa.Uuid()),
    sa.column("system_key", sa.String()),
    sa.column("closed_on", sa.Date()),
)
postings = sa.table(
    "postings",
    sa.column("pid", sa.Uuid()),
    sa.column("transaction", sa.Uuid()),
    sa.column("account", sa.Uuid()),
    sa.column("side", sa.String()),
    sa.column("amount", sa.Numeric(24, 8)),
    sa.column("category_id", sa.Uuid()),
)
transactions = sa.table("transactions", sa.column("tid", sa.Uuid()), sa.column("date", sa.Date()))
allocations = sa.table("budget_allocations", sa.column("account_id", sa.Uuid()), sa.column("category_id", sa.Uuid()))
rules = sa.table(
    "recurring_transactions",
    sa.column("rid", sa.Uuid()),
    sa.column("from_account", sa.Uuid()),
    sa.column("to_account", sa.Uuid()),
    sa.column("category_id", sa.Uuid()),
)
rule_rows = sa.table("recurring_postings", sa.column("account", sa.Uuid()), sa.column("category_id", sa.Uuid()))


def upgrade() -> None:
    op.create_table(
        "budget_categories",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bcid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("details", sa.String(length=200), nullable=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("system_key", sa.String(length=40), nullable=True),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.CheckConstraint("kind IN ('spending', 'earning')", name="ck_budget_categories_kind"),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["parent_id"], ["budget_categories.bcid"]),
        sa.PrimaryKeyConstraint("bcid"),
    )
    op.create_index(op.f("ix_budget_categories_user"), "budget_categories", ["user"], unique=False)
    op.create_index(
        "uq_budget_categories_user_system_key",
        "budget_categories",
        ["user", "system_key"],
        unique=True,
        sqlite_where=sa.text("system_key IS NOT NULL"),
        postgresql_where=sa.text("system_key IS NOT NULL"),
    )
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("category_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_accounts_category_id", "budget_categories", ["category_id"], ["bcid"])
        batch.create_index("ix_accounts_category_id", ["category_id"])
    with op.batch_alter_table("postings") as batch:
        batch.add_column(sa.Column("category_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_postings_category_id", "budget_categories", ["category_id"], ["bcid"])
        batch.create_index("ix_postings_category_id", ["category_id"])
    with op.batch_alter_table("budget_allocations") as batch:
        batch.alter_column("account_id", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("category_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_budget_allocations_category_id", "budget_categories", ["category_id"], ["bcid"])
        batch.create_index("ix_budget_allocations_category_id", ["category_id"])
        batch.create_index("uq_budget_allocations_category", ["user", "month", "category_id"], unique=True)
    with op.batch_alter_table("recurring_transactions") as batch:
        batch.add_column(sa.Column("category_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_recurring_transactions_category_id", "budget_categories", ["category_id"], ["bcid"]
        )
    with op.batch_alter_table("recurring_postings") as batch:
        batch.add_column(sa.Column("category_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_recurring_postings_category_id", "budget_categories", ["category_id"], ["bcid"])
    fill(op.get_bind())


def roots_of(rows: dict) -> dict:
    """Each account's root account (None for one that hangs in the air)."""
    found: dict = {}
    for aid in rows:
        seen = set()
        current = aid
        while rows[current].parent_id is not None and rows[current].parent_id in rows and current not in seen:
            seen.add(current)
            current = rows[current].parent_id
        found[aid] = current if rows[current].parent_id is None else None
    return found


def fill(conn) -> None:
    """Make a category for every Income and Expenses account below the roots and point everything at them."""
    rows = {r.aid: r for r in conn.execute(sa.select(*accounts.c))}
    root = roots_of(rows)
    kind_of = {
        aid: ROOT_KINDS.get(rows[root[aid]].name)
        for aid in rows
        if root[aid] is not None and rows[aid].parent_id is not None
    }
    kind_of = {aid: kind for aid, kind in kind_of.items() if kind}

    def depth(aid) -> int:
        n = 0
        while rows[aid].parent_id in kind_of:
            aid = rows[aid].parent_id
            n += 1
        return n

    now = datetime.now(UTC)
    ordered = sorted(kind_of, key=depth)
    if ordered:
        conn.execute(
            sa.insert(categories),
            [
                {
                    "created": now,
                    "updated": now,
                    "bcid": aid,
                    "user": rows[aid].user,
                    "name": rows[aid].name,
                    "details": rows[aid].details,
                    "kind": kind_of[aid],
                    # A category directly under a root has no group.
                    "parent_id": rows[aid].parent_id if rows[aid].parent_id in kind_of else None,
                    "system_key": None,
                    "closed_on": rows[aid].closed_on,
                }
                for aid in ordered
            ],
        )
        conn.execute(sa.update(accounts).where(accounts.c.aid.in_(list(kind_of))).values(category_id=accounts.c.aid))
        conn.execute(
            sa.update(allocations)
            .where(allocations.c.account_id.in_([a for a, k in kind_of.items() if k == "spending"]))
            .values(category_id=allocations.c.account_id)
        )
    # Each line carries the category of its account.
    own = sa.select(accounts.c.category_id).where(accounts.c.aid == postings.c.account).scalar_subquery()
    conn.execute(sa.update(postings).values(category_id=own))
    # A debit into an account outside the budget that has a payment category, in an entry that touches the budget,
    # carries that category: it is what the budget counted as spending.
    lender_account, paying = accounts.alias("lender"), accounts.alias("paying")
    paid = (
        sa.select(paying.c.category_id)
        .select_from(paying.join(lender_account, lender_account.c.payment_category_id == paying.c.aid))
        .where(lender_account.c.aid == postings.c.account)
        .scalar_subquery()
    )
    touches_budget = (
        sa.select(postings.c.transaction)
        .join(accounts, accounts.c.aid == postings.c.account)
        .where(accounts.c.on_budget.is_(True))
    )
    lender = sa.select(accounts.c.aid).where(
        accounts.c.payment_category_id.is_not(None), accounts.c.on_budget.is_(False)
    )
    conn.execute(
        sa.update(postings)
        .where(
            postings.c.side == "DEBIT",
            postings.c.category_id.is_(None),
            postings.c.account.in_(lender),
            postings.c.transaction.in_(touches_budget),
        )
        .values(category_id=paid)
    )
    # Recurring rules: a simple rule's category is that of its income/expense account, else its lender's payment category.
    by_account: dict = {}
    for aid in rows:
        if aid in kind_of:
            by_account[aid] = aid
        elif rows[aid].payment_category_id in kind_of and not rows[aid].on_budget:
            by_account[aid] = rows[aid].payment_category_id
    for rule in conn.execute(sa.select(rules.c.rid, rules.c.from_account, rules.c.to_account)).all():
        category = next(
            (by_account.get(a) for a in (rule.to_account, rule.from_account) if a is not None and by_account.get(a)),
            None,
        )
        if category is not None:
            conn.execute(sa.update(rules).where(rules.c.rid == rule.rid).values(category_id=category))
    own_row = sa.select(accounts.c.category_id).where(accounts.c.aid == rule_rows.c.account).scalar_subquery()
    conn.execute(sa.update(rule_rows).values(category_id=own_row))
    check(conn)


def spending_before(conn) -> dict:
    """Spending by (month, category) the way the budget counted it: postings to an Expenses account, and debits into an
    account outside the budget that has a payment category, in entries that touch the budget."""
    rows = {r.aid: r for r in conn.execute(sa.select(*accounts.c))}
    spending = {r.bcid for r in conn.execute(sa.select(categories.c.bcid).where(categories.c.kind == "spending"))}
    expense = {aid for aid, a in rows.items() if a.category_id in spending}
    return _total(conn, rows, lambda p: _old_target(rows, expense, p))


def _old_target(rows, expense, p):
    if p.account in expense:
        return p.account
    a = rows[p.account]
    if p.side == "DEBIT" and not a.on_budget and a.payment_category_id in expense:
        return a.payment_category_id
    return None


def _total(conn, rows, target) -> dict:
    touching = {
        p.transaction
        for p in conn.execute(sa.select(postings.c.transaction, postings.c.account))
        if rows[p.account].on_budget
    }
    day = {t.tid: t.date for t in conn.execute(sa.select(transactions.c.tid, transactions.c.date))}
    totals: dict = defaultdict(lambda: ZERO)
    for p in conn.execute(
        sa.select(
            postings.c.transaction, postings.c.account, postings.c.side, postings.c.amount, postings.c.category_id
        )
    ):
        if p.transaction not in touching:
            continue
        category = target(p)
        if category is None:
            continue
        value = Decimal(p.amount) if p.side == "DEBIT" else -Decimal(p.amount)
        d = day[p.transaction]
        d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
        totals[(d.replace(day=1), category)] += value
    return {k: v for k, v in totals.items() if v != 0}


def spending_after(conn) -> dict:
    """The same figures from the categories on the lines: a line counts when its own account is not in the budget."""
    rows = {r.aid: r for r in conn.execute(sa.select(*accounts.c))}
    spending = {r.bcid for r in conn.execute(sa.select(categories.c.bcid).where(categories.c.kind == "spending"))}

    def target(p):
        if p.category_id in spending and not rows[p.account].on_budget:
            return p.category_id
        return None

    return _total(conn, rows, target)


def check(conn) -> None:
    before, after = spending_before(conn), spending_after(conn)
    if before != after:
        wrong = sorted(set(before) ^ set(after) | {k for k in before if k in after and before[k] != after[k]})
        raise RuntimeError(
            f"Budget categories would change what the budget shows ({len(wrong)} month/category figures differ, "
            f"first: {wrong[0]}); nothing was changed."
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT count(*) FROM budget_allocations WHERE account_id IS NULL")).scalar():
        raise RuntimeError("A plan row has no account (its category was made after this migration); cannot go back.")
    with op.batch_alter_table("recurring_postings") as batch:
        batch.drop_constraint("fk_recurring_postings_category_id", type_="foreignkey")
        batch.drop_column("category_id")
    with op.batch_alter_table("recurring_transactions") as batch:
        batch.drop_constraint("fk_recurring_transactions_category_id", type_="foreignkey")
        batch.drop_column("category_id")
    with op.batch_alter_table("budget_allocations") as batch:
        batch.drop_index("uq_budget_allocations_category")
        batch.drop_index("ix_budget_allocations_category_id")
        batch.drop_constraint("fk_budget_allocations_category_id", type_="foreignkey")
        batch.drop_column("category_id")
        batch.alter_column("account_id", existing_type=sa.Uuid(), nullable=False)
    with op.batch_alter_table("postings") as batch:
        batch.drop_index("ix_postings_category_id")
        batch.drop_constraint("fk_postings_category_id", type_="foreignkey")
        batch.drop_column("category_id")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_index("ix_accounts_category_id")
        batch.drop_constraint("fk_accounts_category_id", type_="foreignkey")
        batch.drop_column("category_id")
    op.drop_index("uq_budget_categories_user_system_key", table_name="budget_categories")
    op.drop_index(op.f("ix_budget_categories_user"), table_name="budget_categories")
    op.drop_table("budget_categories")
