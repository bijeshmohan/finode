"""The migration for shared expenses adds empty tables with their checks, leaves the ledger alone and can be undone."""

import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "d9f1b3c5e7a4"
HEAD = "e0a2c4d6f8b5"
TABLES = {"shared_expenses", "expense_shares", "expense_contributions"}


def test_upgrade_adds_the_tables_and_downgrade_removes_them(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    assert not TABLES & set(sa.inspect(engine).get_table_names())
    with engine.begin() as conn:
        entries = conn.execute(sa.text("SELECT count(*) FROM transactions")).scalar()
    command.upgrade(config, HEAD)
    assert set(sa.inspect(engine).get_table_names()) >= TABLES
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM transactions")).scalar() == entries
        for table in TABLES:
            assert conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar() == 0
    command.downgrade(config, PREVIOUS)
    assert not TABLES & set(sa.inspect(engine).get_table_names())
