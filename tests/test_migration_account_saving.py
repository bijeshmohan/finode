"""The saving migration adds the flag (false for every existing account) and can be undone."""

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


def test_upgrade_adds_the_flag_off_and_downgrade_removes_it(alembic):
    config, engine = alembic
    command.upgrade(config, "c8f0b2d4e6a1")
    assert "saving" not in {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
    command.upgrade(config, "d1e3f5a7b9c2")
    column = next(c for c in sa.inspect(engine).get_columns("accounts") if c["name"] == "saving")
    assert column["nullable"] is False
    command.downgrade(config, "c8f0b2d4e6a1")
    assert "saving" not in {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
