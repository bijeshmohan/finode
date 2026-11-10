"""The migration that drops a loan's usual category for payments: the column and its foreign key go, nothing else moves
(a payment keeps the label it has), and going back adds the column again, empty."""

import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "b4d6f8a0c2e5"
HEAD = "c6e8a0b2d4f7"


def rows(conn):
    return {
        table: conn.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar()
        for table in ("accounts", "postings", "transactions", "budget_categories", "budget_allocations")
    }


def test_the_column_goes_and_every_row_and_label_stays(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    with engine.begin() as conn:
        before = rows(conn)
        labels = set(conn.execute(sa.text("SELECT id, category_id FROM postings")).all())
        assert "payment_category_id" in {c["name"] for c in sa.inspect(conn).get_columns("accounts")}
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        assert rows(conn) == before, "no row was added or lost"
        assert "payment_category_id" not in {c["name"] for c in sa.inspect(conn).get_columns("accounts")}
        assert set(conn.execute(sa.text("SELECT id, category_id FROM postings")).all()) == labels, "labels untouched"


def test_going_back_adds_the_column_empty(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    with engine.begin() as conn:
        assert (
            conn.execute(sa.text("SELECT count(*) FROM accounts WHERE payment_category_id IS NOT NULL")).scalar() == 0
        )
    command.upgrade(config, HEAD)
