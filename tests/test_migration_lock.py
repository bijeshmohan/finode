"""profiles.locked_through is added without locking anybody, and can be undone."""

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


def test_upgrade_leaves_existing_profiles_unlocked_and_downgrade_removes_the_column(alembic):
    config, engine = alembic
    command.upgrade(config, "c9e1a3b5d7f2")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(sa.text(
            "INSERT INTO profiles (user, max_depth_assets, max_depth_liabilities, max_depth_equity, max_depth_income, "
            "max_depth_expenses, created, updated) VALUES ('00000000-0000-4000-8000-0000000000aa', 0, 0, 0, 0, 0, "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ))
    command.upgrade(config, "d1f3b5c7e9a4")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT locked_through FROM profiles")).scalar() is None
    command.downgrade(config, "c9e1a3b5d7f2")
    assert "locked_through" not in {c["name"] for c in sa.inspect(engine).get_columns("profiles")}
