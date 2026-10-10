"""The split-recurring migration keeps plain rules as they are and can be undone."""

from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

PARENT = "c7e9a1b3d458"
USER = uuid4()
NOW = datetime.now(timezone.utc)


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    yield Config("alembic.ini"), engine
    engine.dispose()


def test_a_plain_rule_survives_and_the_new_shape_fits(alembic):
    config, engine = alembic
    command.upgrade(config, PARENT)
    bank, rent, rid = uuid4(), uuid4(), uuid4()
    with engine.begin() as c:
        for aid, name in ((bank, "Bank"), (rent, "Rent")):
            c.execute(
                sa.text("INSERT INTO accounts (created, updated, aid, user, name) VALUES (:n, :n, :a, :u, :name)").bindparams(
                    sa.bindparam("a", aid, type_=sa.Uuid()), sa.bindparam("u", USER, type_=sa.Uuid()),
                    sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)), sa.bindparam("name", name),
                )
            )
        c.execute(
            sa.text(
                "INSERT INTO recurring_transactions (created, updated, rid, user, from_account, to_account, amount, frequency, every, "
                "start_date, next_date, active) VALUES (:n, :n, :r, :u, :f, :t, 5, 'monthly', 1, :d, :d, 1)"
            ).bindparams(
                sa.bindparam("r", rid, type_=sa.Uuid()), sa.bindparam("u", USER, type_=sa.Uuid()),
                sa.bindparam("f", bank, type_=sa.Uuid()), sa.bindparam("t", rent, type_=sa.Uuid()),
                sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)), sa.bindparam("d", date(2026, 1, 1), type_=sa.Date()),
            )
        )
    command.upgrade(config, "d9f1b3c5e679")
    inspector = sa.inspect(engine)
    assert "recurring_postings" in inspector.get_table_names()
    columns = {c["name"]: c for c in inspector.get_columns("recurring_transactions")}
    assert "currency" in columns and columns["from_account"]["nullable"] and columns["amount"]["nullable"]
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM recurring_transactions WHERE amount IS NOT NULL")).scalar() == 1

    command.downgrade(config, PARENT)
    assert "recurring_postings" not in sa.inspect(engine).get_table_names()
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM recurring_transactions")).scalar() == 1
