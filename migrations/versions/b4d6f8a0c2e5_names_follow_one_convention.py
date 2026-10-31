"""Names follow one convention: every key is `id`, every reference is `<entity>_id`, the owner is `user_id`

Revision ID: b4d6f8a0c2e5
Revises: f5b7d9e1a3c4
Create Date: 2026-10-31 18:00:00.000000

The tables grew bespoke key codes (`aid`, `tid`, `pid`, `bcid`...) and an owner column called `user`, a reserved word in
Postgres. Now a table's primary key is `id`, a column that points at another table is `<entity>_id` (`account_id`,
`transaction_id`, `recurring_id`, `from_account_id`...) and the owner is `user_id`. Only names change: no row, type or
constraint does, so the migration can be undone. The plan is `docs/developer/naming-plan.md`.

Postgres renames a column in place (indexes, keys and foreign keys follow it); an index whose name spelled the old column
is renamed with `ALTER INDEX`. SQLite (the tests) renames columns in place too but has no rename for an index, so those
are dropped and made again.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4d6f8a0c2e5"
down_revision: str | Sequence[str] | None = "f5b7d9e1a3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> {old column: new column}
COLUMNS: dict[str, dict[str, str]] = {
    "accounts": {"aid": "id", "user": "user_id"},
    "account_deletions": {"did": "id", "user": "user_id"},
    "account_history": {"hid": "id", "user": "user_id"},
    "api_tokens": {"tkid": "id", "user": "user_id"},
    "budget_allocations": {"bid": "id", "user": "user_id"},
    "budget_categories": {"bcid": "id", "user": "user_id"},
    "goal_allocations": {"gaid": "id", "user": "user_id"},
    "goals": {"gid": "id", "user": "user_id"},
    "oauth_grants": {"gid": "id", "user": "user_id"},
    "postings": {"pid": "id", "user": "user_id", "transaction": "transaction_id", "account": "account_id"},
    "profiles": {"user": "user_id"},
    "recurring_postings": {"rpid": "id", "user": "user_id", "rid": "recurring_id", "account": "account_id"},
    "recurring_transactions": {
        "rid": "id",
        "user": "user_id",
        "from_account": "from_account_id",
        "to_account": "to_account_id",
    },
    "tags": {"tgid": "id", "user": "user_id"},
    "transaction_history": {"hid": "id", "user": "user_id"},
    "transaction_tags": {"user": "user_id"},
    "transactions": {"tid": "id", "user": "user_id"},
}

# The automatic index names that spelled an old column: table -> {old index: (new index, new columns)}
INDEXES: dict[str, dict[str, tuple[str, list[str]]]] = {
    table: {f"ix_{table}_user": (f"ix_{table}_user_id", ["user_id"])} for table in COLUMNS if table != "profiles"
}
INDEXES["postings"] |= {
    "ix_postings_account": ("ix_postings_account_id", ["account_id"]),
    "ix_postings_transaction": ("ix_postings_transaction_id", ["transaction_id"]),
}
INDEXES["recurring_postings"] |= {
    "ix_recurring_postings_rid": ("ix_recurring_postings_recurring_id", ["recurring_id"]),
}


def _rename_columns(table: str, pairs: dict[str, str]) -> None:
    for old, new in pairs.items():
        op.execute(sa.text(f'ALTER TABLE {table} RENAME COLUMN "{old}" TO "{new}"'))


def _rename_index(table: str, old: str, new: str, columns: list[str]) -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text(f'ALTER INDEX "{old}" RENAME TO "{new}"'))
    else:
        op.drop_index(old, table_name=table)
        op.create_index(new, table, columns)


def upgrade() -> None:
    for table, pairs in COLUMNS.items():
        _rename_columns(table, pairs)
    for table, renames in INDEXES.items():
        for old, (new, columns) in renames.items():
            _rename_index(table, old, new, columns)


def downgrade() -> None:
    for table, pairs in COLUMNS.items():
        _rename_columns(table, {new: old for old, new in pairs.items()})
    for table, renames in INDEXES.items():
        back = {new: old for old, new in COLUMNS[table].items()}
        for old, (new, columns) in renames.items():
            _rename_index(table, new, old, [back.get(column, column) for column in columns])
