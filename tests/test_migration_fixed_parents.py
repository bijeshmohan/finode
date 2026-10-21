"""The fixed-parents migration: a nullable key on accounts, nothing filled in for anybody who already has accounts; it can be undone."""

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


def test_the_key_is_added_empty_and_unique_per_person(alembic):
    config, engine = alembic
    command.upgrade(config, "a7c9e1b3d5f2")
    user = "00000000-0000-4000-8000-000000000001"
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
        conn.execute(sa.text('INSERT INTO accounts (aid, "user", name, on_budget, saving, created, updated) VALUES (:a, :u, \'Assets\', 0, 0, \'2026-10-01\', \'2026-10-01\')'), {"a": "a" * 32, "u": user})
    command.upgrade(config, "b9d1f3a5c7e2")
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT system_key FROM accounts")).scalars().all() == [None], "nobody's accounts are keyed"
        conn.execute(sa.text('INSERT INTO accounts (aid, "user", name, parent_id, on_budget, saving, system_key, created, updated) VALUES (:a, :u, \'Cash\', :p, 0, 0, \'assets.cash\', \'2026-10-01\', \'2026-10-01\')'), {"a": "b" * 32, "u": user, "p": "a" * 32})
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(sa.text('INSERT INTO accounts (aid, "user", name, parent_id, on_budget, saving, system_key, created, updated) VALUES (:a, :u, \'Cash 2\', :p, 0, 0, \'assets.cash\', \'2026-10-01\', \'2026-10-01\')'), {"a": "c" * 32, "u": user, "p": "a" * 32})
    command.downgrade(config, "a7c9e1b3d5f2")
    assert "system_key" not in {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
