"""The migration that removes budget targets drops the table and can be undone (an empty table comes back)."""

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


def test_upgrade_drops_the_table_and_downgrade_brings_it_back_empty(alembic):
    config, engine = alembic
    command.upgrade(config, "e7b9d1f3a5c8")
    assert "budget_targets" in sa.inspect(engine).get_table_names()
    command.upgrade(config, "f2c4e6a8b0d1")
    assert "budget_targets" not in sa.inspect(engine).get_table_names()
    command.downgrade(config, "e7b9d1f3a5c8")
    inspector = sa.inspect(engine)
    assert "budget_targets" in inspector.get_table_names()
    assert {c["name"] for c in inspector.get_columns("budget_targets")} >= {"tgid", "user", "account_id", "kind", "amount", "target_date", "weekday"}
    with engine.connect() as connection:
        assert connection.execute(sa.text("select count(*) from budget_targets")).scalar() == 0
