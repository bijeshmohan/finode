"""The migration that lets a recurring rule carry tags: old rules have none, and it can be undone."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "a2c4e6f8b1d3"
AFTER = "b3d5f7a9c1e2"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def test_old_rules_get_no_tags_and_the_column_can_be_dropped(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    with engine.begin() as c:
        c.execute(
            sa.text(
                'INSERT INTO recurring_transactions (created, updated, rid, "user", frequency, every, start_date, next_date, active) '
                "VALUES ('2026-01-01', '2026-01-01', 'a1', 'u1', 'monthly', 1, '2026-01-01', '2026-01-01', 1)"
            )
        )
    command.upgrade(config, AFTER)
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT tags FROM recurring_transactions")).scalar_one() == "[]"
    command.downgrade(config, BEFORE)
    assert "tags" not in {c["name"] for c in sa.inspect(engine).get_columns("recurring_transactions")}
