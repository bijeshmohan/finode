"""The migration that adds the account history table: it starts empty, takes rows with known actions only, and can be undone."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "d3f5b7c9e1a2"
AFTER = "e5a7c9b1d3f4"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def add(engine, action):
    with engine.begin() as c:
        c.execute(
            sa.text(
                'INSERT INTO account_history (hid, "user", account_id, action, at, snapshot) '
                "VALUES (:h, :u, :a, :action, :at, '{}')"
            ).bindparams(
                sa.bindparam("h", uuid4(), type_=sa.Uuid()),
                sa.bindparam("u", uuid4(), type_=sa.Uuid()),
                sa.bindparam("a", uuid4(), type_=sa.Uuid()),
                sa.bindparam("action", action),
                sa.bindparam("at", datetime.now(UTC), type_=sa.DateTime(timezone=True)),
            )
        )


def test_the_table_comes_empty_and_checks_its_actions(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    assert "account_history" not in sa.inspect(engine).get_table_names()
    command.upgrade(config, AFTER)
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM account_history")).scalar_one() == 0
    add(engine, "closed")
    with pytest.raises(sa.exc.IntegrityError):
        add(engine, "exploded")


def test_it_can_be_undone(alembic):
    config, engine = alembic
    command.upgrade(config, AFTER)
    command.downgrade(config, BEFORE)
    assert "account_history" not in sa.inspect(engine).get_table_names()
