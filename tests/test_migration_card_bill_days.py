"""The migration that adds a card's statement day and due day: two empty columns, checks that keep them honest, and a
downgrade that removes them."""

import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "c6e8a0b2d4f7"
HEAD = "d8f0b2c4e6a9"


def columns(conn):
    return {c["name"] for c in sa.inspect(conn).get_columns("accounts")}


def test_the_columns_are_added_empty_and_every_account_stays(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    with engine.begin() as conn:
        before = conn.execute(sa.text("SELECT count(*) FROM accounts")).scalar()
        assert "statement_day" not in columns(conn)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        assert {"statement_day", "due_day"} <= columns(conn)
        assert conn.execute(sa.text("SELECT count(*) FROM accounts")).scalar() == before
        assert conn.execute(sa.text("SELECT count(*) FROM accounts WHERE statement_day IS NOT NULL")).scalar() == 0


def test_the_database_refuses_days_out_of_range_or_alone(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        victim = conn.execute(sa.text("SELECT id FROM accounts LIMIT 1")).scalar()
    for values in ("statement_day = 0, due_day = 5", "statement_day = 32, due_day = 5", "statement_day = 5"):
        try:
            with engine.begin() as conn:
                conn.execute(sa.text(f"UPDATE accounts SET {values} WHERE id = :id"), {"id": victim})
        except sa.exc.IntegrityError:
            continue
        raise AssertionError(f"accepted: {values}")


def test_going_back_drops_the_columns(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    with engine.begin() as conn:
        assert not ({"statement_day", "due_day"} & columns(conn))
