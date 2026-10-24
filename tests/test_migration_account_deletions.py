"""The migration that adds the record of deleted accounts: the table appears, empty, and goes again."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "b6d8f0a2c4e7"
AFTER = "c8f0b2d4e6a1"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def test_the_table_comes_and_goes(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    assert "account_deletions" not in sa.inspect(engine).get_table_names()
    command.upgrade(config, AFTER)
    inspector = sa.inspect(engine)
    assert "account_deletions" in inspector.get_table_names()
    assert {c["name"] for c in inspector.get_columns("account_deletions")} == {
        "did",
        "user",
        "account_id",
        "at",
        "snapshot",
    }
    command.downgrade(config, BEFORE)
    assert "account_deletions" not in sa.inspect(engine).get_table_names()
