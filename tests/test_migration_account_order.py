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
