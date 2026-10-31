"""The migration that gives every table one naming convention: keys are `id`, references are `<entity>_id`, the owner is
`user_id`. Only names change, so every row survives, the references still line up, and going back restores the old names."""

import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "f5b7d9e1a3c4"
HEAD = "b4d6f8a0c2e5"
RENAMED = {
    "accounts": ("aid", "id"),
    "transactions": ("tid", "id"),
    "postings": ("pid", "id"),
    "budget_categories": ("bcid", "id"),
    "budget_allocations": ("bid", "id"),
    "recurring_transactions": ("rid", "id"),
    "recurring_postings": ("rpid", "id"),
}


def counts(conn):
    tables = [t for t in sa.inspect(conn).get_table_names() if t != "alembic_version"]
    return {t: conn.execute(sa.text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}


def test_every_table_is_renamed_and_every_row_and_reference_survives(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    with engine.begin() as conn:
        before = counts(conn)
        old_pairs = set(conn.execute(sa.text('SELECT "transaction", account FROM postings')).all())
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        assert counts(conn) == before, "no row was added or lost"
        inspector = sa.inspect(conn)
        for table, (old, new) in RENAMED.items():
            columns = {c["name"] for c in inspector.get_columns(table)}
            assert new in columns and old not in columns, table
        for table in before:
            columns = {c["name"] for c in inspector.get_columns(table)}
            assert "user" not in columns, f"{table} still has a column called user"
        assert {c["name"] for c in inspector.get_columns("postings")} >= {"transaction_id", "account_id", "user_id"}
        assert {c["name"] for c in inspector.get_columns("recurring_transactions")} >= {
            "from_account_id",
            "to_account_id",
        }
        assert {c["name"] for c in inspector.get_columns("recurring_postings")} >= {"recurring_id", "account_id"}
        new_pairs = set(conn.execute(sa.text("SELECT transaction_id, account_id FROM postings")).all())
        assert new_pairs == old_pairs, "the lines still point at the same entries and accounts"
        orphans = conn.execute(
            sa.text(
                "SELECT count(*) FROM postings p LEFT JOIN accounts a ON a.id = p.account_id "
                "LEFT JOIN transactions t ON t.id = p.transaction_id WHERE a.id IS NULL OR t.id IS NULL"
            )
        ).scalar()
        assert orphans == 0
        indexes = {i["name"] for t in before for i in inspector.get_indexes(t)}
        assert "ix_postings_account_id" in indexes and "ix_accounts_user_id" in indexes
        assert "ix_accounts_user" not in indexes


def test_going_back_restores_the_old_names_and_keeps_the_rows(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        before = counts(conn)
    command.downgrade(config, PREVIOUS)
    with engine.begin() as conn:
        assert counts(conn) == before
        inspector = sa.inspect(conn)
        for table, (old, new) in RENAMED.items():
            columns = {c["name"] for c in inspector.get_columns(table)}
            assert old in columns and new not in columns, table
        assert "ix_postings_account" in {i["name"] for i in inspector.get_indexes("postings")}
    command.upgrade(config, HEAD)
