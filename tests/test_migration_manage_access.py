"""The migration that lets a token or an app be allowed to manage accounts: old rows stay, 'manage' is accepted, and undoing it makes them 'write'."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "c1e3a5b7d9f0"
AFTER = "d3f5b7c9e1a2"
NOW = datetime.now(UTC)


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def add_token(engine, scope, name):
    with engine.begin() as c:
        c.execute(
            sa.text(
                'INSERT INTO api_tokens (created, updated, tkid, "user", name, scope, token_hash, prefix) '
                "VALUES (:n, :n, :t, :u, :name, :scope, :h, 'fin_x')"
            ).bindparams(
                sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)),
                sa.bindparam("t", uuid4(), type_=sa.Uuid()),
                sa.bindparam("u", uuid4(), type_=sa.Uuid()),
                sa.bindparam("name", name),
                sa.bindparam("scope", scope),
                sa.bindparam("h", uuid4().hex + uuid4().hex),
            )
        )


def test_manage_is_accepted_and_old_rows_stay(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    add_token(engine, "write", "old")
    with pytest.raises(sa.exc.IntegrityError):
        add_token(engine, "manage", "too early")
    command.upgrade(config, AFTER)
    add_token(engine, "manage", "new")
    with pytest.raises(sa.exc.IntegrityError):
        add_token(engine, "admin", "nonsense")
    with engine.connect() as c:
        rows = dict(c.execute(sa.text("SELECT name, scope FROM api_tokens")).all())
    assert rows == {"old": "write", "new": "manage"}


def test_undoing_it_turns_manage_into_write(alembic):
    config, engine = alembic
    command.upgrade(config, AFTER)
    add_token(engine, "manage", "m")
    command.downgrade(config, BEFORE)
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT scope FROM api_tokens")).scalar_one() == "write"
    with pytest.raises(sa.exc.IntegrityError):
        add_token(engine, "manage", "again")
