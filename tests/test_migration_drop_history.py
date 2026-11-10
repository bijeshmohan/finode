"""The migration that removes all history drops the three tables, leaves the ledger alone, and can be undone (empty
tables come back)."""

import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "a6c8e0b2d4f1"
HEAD = "b7d9f1a3c5e2"
TABLES = {"transaction_history", "account_history", "account_deletions"}


def test_upgrade_drops_the_tables_and_the_ledger_stays(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    assert set(sa.inspect(engine).get_table_names()) >= TABLES
    with engine.begin() as conn:
        entries = conn.execute(sa.text("SELECT count(*) FROM transactions")).scalar()
        accounts = conn.execute(sa.text("SELECT count(*) FROM accounts")).scalar()
    command.upgrade(config, HEAD)
    assert not TABLES & set(sa.inspect(engine).get_table_names())
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM transactions")).scalar() == entries
        assert conn.execute(sa.text("SELECT count(*) FROM accounts")).scalar() == accounts


def test_downgrade_brings_back_empty_tables(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    inspector = sa.inspect(engine)
    assert set(inspector.get_table_names()) >= TABLES
    assert {c["name"] for c in inspector.get_columns("transaction_history")} >= {
        "id",
        "user_id",
        "transaction_id",
        "action",
        "at",
        "via",
        "snapshot",
    }
    with engine.connect() as conn:
        for table in TABLES:
            assert conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar() == 0
    command.downgrade(config, "e1a3c5b7d9f2")  # and one step further still works
