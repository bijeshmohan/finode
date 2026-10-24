"""The migration that removes the Advanced switch drops the column and can be undone (switched off)."""

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


def test_upgrade_drops_the_column_and_downgrade_adds_it_back_off(alembic):
    config, engine = alembic
    command.upgrade(config, "f2c4e6a8b0d1")
    assert "advanced" in {c["name"] for c in sa.inspect(engine).get_columns("profiles")}
    command.upgrade(config, "a9b1c3d5e7f2")
    assert "advanced" not in {c["name"] for c in sa.inspect(engine).get_columns("profiles")}
    command.downgrade(config, "f2c4e6a8b0d1")
    assert "advanced" in {c["name"] for c in sa.inspect(engine).get_columns("profiles")}
