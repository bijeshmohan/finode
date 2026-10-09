"""The targets migration creates the table and can be undone."""

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


def test_upgrade_and_downgrade(alembic):
    config, engine = alembic
    command.upgrade(config, "c7e9a1b3d458")
    inspector = sa.inspect(engine)
    assert "budget_targets" in inspector.get_table_names()
    assert {c["name"] for c in inspector.get_columns("budget_targets")} >= {"tgid", "user", "account_id", "kind", "amount", "target_date"}
    command.downgrade(config, "b5d7f9a1c346")
    assert "budget_targets" not in sa.inspect(engine).get_table_names()
