"""Pinned and position are added to accounts, with nothing pinned or placed to begin with, and can be undone."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    yield Config("alembic.ini"), engine
    engine.dispose()


def test_upgrade_keeps_existing_accounts_unpinned_and_downgrade_removes_the_columns(alembic):
    config, engine = alembic
    command.upgrade(config, "f3b5d7e9a1c2")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(sa.text(
            "INSERT INTO accounts (aid, user, name, on_budget, created, updated) "
            "VALUES ('00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-0000000000aa', 'Old', 0, "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ))
    command.upgrade(config, "b8d0f2a4c6e1")
    columns = {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
    assert {"pinned", "position"} <= columns
    with engine.connect() as connection:
        row = connection.execute(sa.text("SELECT pinned, position FROM accounts")).one()
    assert not row.pinned and row.position is None
    command.downgrade(config, "a7c9e1b3d5f6")
    assert not {"pinned", "position"} & {c["name"] for c in sa.inspect(engine).get_columns("accounts")}


def test_skipped_date_is_added_to_recurring_transactions_and_removed(alembic):
    config, engine = alembic
    command.upgrade(config, "c9e1a3b5d7f2")
    assert "skipped_date" in {c["name"] for c in sa.inspect(engine).get_columns("recurring_transactions")}
    command.downgrade(config, "b8d0f2a4c6e1")
    assert "skipped_date" not in {c["name"] for c in sa.inspect(engine).get_columns("recurring_transactions")}


def test_advanced_switch_is_on_for_existing_profiles_and_can_be_undone(alembic):
    config, engine = alembic
    command.upgrade(config, "d1f3b5c7e9a4")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(sa.text(
            "INSERT INTO profiles (user, max_depth_assets, max_depth_liabilities, max_depth_equity, max_depth_income, "
            "max_depth_expenses, created, updated) VALUES ('00000000-0000-4000-8000-0000000000aa', 0, 0, 0, 0, 0, "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ))
    command.upgrade(config, "e2a4c6e8f1b3")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT advanced FROM profiles")).scalar() in (1, True), "nothing disappears on deploy"
    command.downgrade(config, "d1f3b5c7e9a4")
    assert "advanced" not in {c["name"] for c in sa.inspect(engine).get_columns("profiles")}
