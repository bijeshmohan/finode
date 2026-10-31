"""The two-levels migration: the depth limits leave the profile; deeper accounts stop it, changing nothing."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "f4b6d8a0c2e5"
NOW = datetime.now(UTC)
USER = uuid4()


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def _chain(engine, depth):
    """A root and `depth` accounts below it, each inside the one before."""
    parent = None
    with engine.begin() as c:
        for level in range(depth + 1):
            aid = uuid4()
            c.execute(
                sa.text(
                    "INSERT INTO accounts (created, updated, aid, user, name, parent_id) VALUES (:n, :n, :a, :u, :name, :p)"
                ).bindparams(
                    sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)),
                    sa.bindparam("a", aid, type_=sa.Uuid()),
                    sa.bindparam("u", USER, type_=sa.Uuid()),
                    sa.bindparam("name", "Expenses" if level == 0 else f"Level {level}"),
                    sa.bindparam("p", parent, type_=sa.Uuid()),
                )
            )
            parent = aid


def test_the_limits_go_and_the_accounts_stay(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    _chain(engine, 2)
    with engine.begin() as c:
        c.execute(
            sa.text(
                'INSERT INTO profiles (created, updated, "user", max_depth_expenses) VALUES (:n, :n, :u, 3)'
            ).bindparams(
                sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)), sa.bindparam("u", USER, type_=sa.Uuid())
            )
        )
    command.upgrade(config, "head")
    inspector = sa.inspect(engine)
    assert not [c["name"] for c in inspector.get_columns("profiles") if c["name"].startswith("max_depth")]
    with engine.connect() as c:
        # the Expenses accounts became categories (a later migration), so only the root is left
        assert c.execute(sa.text("SELECT count(*) FROM accounts")).scalar() == 1
        assert c.execute(sa.text("SELECT count(*) FROM budget_categories")).scalar() == 2
        assert c.execute(sa.text("SELECT count(*) FROM profiles")).scalar() == 1


def test_a_third_level_stops_the_migration(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    _chain(engine, 3)
    with pytest.raises(RuntimeError, match="more than two levels deep.*Level 3"):
        command.upgrade(config, "head")
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == BEFORE
        assert "max_depth_expenses" in {col["name"] for col in sa.inspect(c).get_columns("profiles")}


def test_it_can_be_undone(alembic):
    config, engine = alembic
    command.upgrade(config, "head")
    command.downgrade(config, BEFORE)
    assert "max_depth_assets" in {c["name"] for c in sa.inspect(engine).get_columns("profiles")}
    command.upgrade(config, "head")
