"""The plan sections migration: Build on for everybody, Earn on for the people who had Advanced on; it can be undone."""

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


def test_earn_follows_advanced_and_build_is_on(alembic):
    config, engine = alembic
    command.upgrade(config, "d1e3f5a7b9c2")
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
        for user, advanced in (("00000000-0000-4000-8000-000000000001", 1), ("00000000-0000-4000-8000-000000000002", 0)):
            conn.execute(sa.text("INSERT INTO profiles (\"user\", currency, advanced, created, updated) VALUES (:u, 'INR', :a, '2026-10-01', '2026-10-01')"), {"u": user, "a": advanced})
    command.upgrade(config, "a7c9e1b3d5f2")
    with engine.connect() as conn:
        rows = conn.execute(sa.text('SELECT advanced, plan_build, plan_earn FROM profiles ORDER BY "user"')).all()
    assert [tuple(map(bool, r)) for r in rows] == [(True, True, True), (False, True, False)]
    command.downgrade(config, "d1e3f5a7b9c2")
    assert "plan_earn" not in {c["name"] for c in sa.inspect(engine).get_columns("profiles")}
