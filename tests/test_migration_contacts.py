"""The contacts migration adds two empty tables (with the role check and the uniqueness the service relies on),
changes nothing else, and can be undone."""

import pytest
import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "b7d9f1a3c5e2"
HEAD = "c8e0a2b4d6f3"
TABLES = {"contacts", "contact_accounts"}


def test_upgrade_adds_the_tables_and_the_ledger_stays(alembic):
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
        assert conn.execute(sa.text("SELECT count(*) FROM contacts")).scalar() == 0


def test_a_role_must_be_receivable_or_payable_and_a_contact_has_one_of_each(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        user = conn.execute(sa.text("SELECT user_id FROM accounts LIMIT 1")).scalar()
        account = conn.execute(sa.text("SELECT id FROM accounts LIMIT 1")).scalar()
        conn.execute(
            sa.text(
                "INSERT INTO contacts (created, updated, id, user_id, name) VALUES (now_, now_, 'c1', :u, 'Alice')".replace(
                    "now_", "'2026-01-01'"
                )
            ),
            {"u": user},
        )

    def link(role, account_id):
        return sa.text(
            "INSERT INTO contact_accounts (created, id, user_id, contact_id, account_id, role) "
            f"VALUES ('2026-01-01', lower(hex(randomblob(16))), :u, 'c1', :a, '{role}')"
        ), {"u": user, "a": account_id}

    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(*link("lender", account))
    with engine.begin() as conn:
        conn.execute(*link("receivable", account))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(*link("receivable", account))


def test_downgrade_drops_the_tables(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    assert not TABLES & set(sa.inspect(engine).get_table_names())
