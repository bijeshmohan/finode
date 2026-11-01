"""The migration that adds a line's posting date and a card's bill rounding: two empty columns, a check on the rule, and a
downgrade that removes them."""

import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "d8f0b2c4e6a9"
HEAD = "e1a3c5b7d9f2"


def columns(conn, table):
    return {c["name"] for c in sa.inspect(conn).get_columns(table)}


def test_the_columns_are_added_and_nothing_else_moves(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    with engine.begin() as conn:
        before = conn.execute(sa.text("SELECT count(*) FROM postings")).scalar()
        assert "posted_on" not in columns(conn, "postings")
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        assert "posted_on" in columns(conn, "postings") and "bill_rounding" in columns(conn, "accounts")
        assert conn.execute(sa.text("SELECT count(*) FROM postings")).scalar() == before
        assert conn.execute(sa.text("SELECT count(*) FROM postings WHERE posted_on IS NOT NULL")).scalar() == 0
        assert conn.execute(sa.text("SELECT count(*) FROM accounts WHERE bill_rounding <> 'none'")).scalar() == 0


def test_the_database_refuses_an_unknown_rule(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        victim = conn.execute(sa.text("SELECT id FROM accounts LIMIT 1")).scalar()
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE accounts SET bill_rounding = 'sometimes' WHERE id = :id"), {"id": victim})
    except sa.exc.IntegrityError:
        return
    raise AssertionError("accepted an unknown rule")


def test_going_back_drops_the_columns(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    with engine.begin() as conn:
        assert "posted_on" not in columns(conn, "postings") and "bill_rounding" not in columns(conn, "accounts")
