"""The migration that removes the period lock and the hand-set account order drops both columns and can be undone."""

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


def columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_upgrade_drops_both_columns_and_downgrade_adds_them_back_empty(alembic):
    config, engine = alembic
    command.upgrade(config, "a9b1c3d5e7f2")
    assert "locked_through" in columns(engine, "profiles") and "position" in columns(engine, "accounts")
    command.upgrade(config, "b2d4f6a8c0e3")
    assert "locked_through" not in columns(engine, "profiles") and "position" not in columns(engine, "accounts")
    command.downgrade(config, "a9b1c3d5e7f2")
    assert "locked_through" in columns(engine, "profiles") and "position" in columns(engine, "accounts")
