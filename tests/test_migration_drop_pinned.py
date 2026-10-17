"""The migration that drops accounts.pinned: the column goes, the accounts stay, and it can be undone."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "a5c7e9b1d3f6"
AFTER = "b6d8f0a2c4e7"
NOW = datetime.now(timezone.utc)


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def columns(engine):
    return {c["name"] for c in sa.inspect(engine).get_columns("accounts")}


def test_the_column_goes_and_comes_back_empty(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    assert "pinned" in columns(engine)
    aid = uuid4()
    with engine.begin() as c:
        c.execute(
            sa.text("INSERT INTO accounts (created, updated, aid, user, name, pinned) VALUES (:n, :n, :a, :u, 'Wallet', 1)").bindparams(
                sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)),
                sa.bindparam("a", aid, type_=sa.Uuid()),
                sa.bindparam("u", uuid4(), type_=sa.Uuid()),
            )
        )
    command.upgrade(config, AFTER)
    assert "pinned" not in columns(engine) and "position" in columns(engine)
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT name FROM accounts")).scalar_one() == "Wallet", "the account stays"
    command.downgrade(config, BEFORE)
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT pinned FROM accounts")).scalar_one() == 0, "nothing is pinned after going back"
