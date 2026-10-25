"""The migration that adds an entry's source and reference: old entries stay, the pair is unique, and it can be undone."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "b2d4f6a8c0e3"
AFTER = "c1e3a5b7d9f0"
NOW = datetime.now(UTC)


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def insert(engine, user, **extra):
    columns = ["created", "updated", "tid", "user", "date", *extra]
    marks = ", ".join(f":{c}" for c in columns)
    with engine.begin() as c:
        c.execute(
            sa.text(
                f"INSERT INTO transactions ({', '.join(chr(34) + k + chr(34) for k in columns)}) VALUES ({marks})"
            ).bindparams(
                sa.bindparam("created", NOW, type_=sa.DateTime(timezone=True)),
                sa.bindparam("updated", NOW, type_=sa.DateTime(timezone=True)),
                sa.bindparam("tid", uuid4(), type_=sa.Uuid()),
                sa.bindparam("user", user, type_=sa.Uuid()),
                sa.bindparam("date", "2026-10-10"),
                *[sa.bindparam(k, v) for k, v in extra.items()],
            )
        )


def test_old_entries_stay_and_the_pair_is_unique(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    user = uuid4()
    insert(engine, user)
    command.upgrade(config, AFTER)
    with engine.connect() as c:
        row = c.execute(sa.text("SELECT source, external_id, source_url FROM transactions")).one()
    assert tuple(row) == (None, None, None)
    insert(engine, user)  # many entries without a reference are fine
    insert(engine, user, source="gmail", external_id="a")
    insert(engine, uuid4(), source="gmail", external_id="a")  # another person may use the same reference
    with pytest.raises(sa.exc.IntegrityError):
        insert(engine, user, source="gmail", external_id="a")


def test_it_can_be_undone(alembic):
    config, engine = alembic
    command.upgrade(config, AFTER)
    command.downgrade(config, BEFORE)
    names = {c["name"] for c in sa.inspect(engine).get_columns("transactions")}
    assert not names & {"source", "external_id", "source_url"}
