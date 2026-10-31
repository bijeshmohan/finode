"""The migration that keeps plan rows against the category alone: the older account key goes, a row without a category
is refused and nothing changes, and going back puts the key back from the category's own account."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

from .test_migration_budget_categories import AFTER, BEFORE, USER, account, seed

HEAD = "e4a6c8d0f2b3"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    yield Config("alembic.ini"), engine
    engine.dispose()


def columns(engine) -> set[str]:
    return {c["name"] for c in sa.inspect(engine).get_columns("budget_allocations")}


def test_the_account_key_goes_and_the_category_stays(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    with engine.begin() as conn:
        seed(conn)
    command.upgrade(config, AFTER)
    assert {"account_id", "category_id"} <= columns(engine)
    command.upgrade(config, HEAD)
    assert "account_id" not in columns(engine) and "category_id" in columns(engine)
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT category_id, amount FROM budget_allocations")).one().category_id == "d" * 32


def test_a_row_without_a_category_is_refused_and_nothing_changes(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    with engine.begin() as conn:
        seed(conn)
        account(conn, "7", "Loose", parent="5")
        conn.execute(
            sa.text(
                'INSERT INTO budget_allocations (bid, "user", month, account_id, amount, created, updated) '
                "VALUES (:b, :u, '2026-09-01', :a, 1, '2026-10-01', '2026-10-01')"
            ),
            {"b": "8" * 32, "u": USER, "a": "1" * 32},  # a plan row on an Assets root: no category
        )
    command.upgrade(config, AFTER)
    with pytest.raises(RuntimeError, match="names no category"):
        command.upgrade(config, HEAD)
    assert "account_id" in columns(engine)


def test_going_back_brings_the_account_key_back(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    with engine.begin() as conn:
        seed(conn)
    command.upgrade(config, HEAD)
    command.downgrade(config, AFTER)
    assert {"account_id", "category_id"} <= columns(engine)
    with engine.begin() as conn:
        row = conn.execute(sa.text("SELECT account_id, category_id FROM budget_allocations")).one()
        assert row.account_id == row.category_id == "d" * 32
