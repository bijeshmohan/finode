"""The order of the four account types is added to every profile, starting in the starting order, and can be undone."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from finode.config import settings


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    yield Config("alembic.ini"), engine
    engine.dispose()


def test_every_profile_starts_in_the_starting_order_and_downgrade_removes_it(alembic):
    config, engine = alembic
    command.upgrade(config, "d7e9a1c3b5f8")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(
            sa.text(
                "INSERT INTO profiles (user_id, currency, created, updated) "
                "VALUES ('00000000-0000-4000-8000-0000000000aa', 'INR', '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        )
    command.upgrade(config, "e8a0c2d4f6b9")
    with engine.connect() as connection:
        order = connection.execute(sa.text("SELECT account_type_order FROM profiles")).scalar_one()
    assert order == "assets.bank,assets.cash,liabilities.cards,assets.wallet"
    command.downgrade(config, "d7e9a1c3b5f8")
    assert "account_type_order" not in {c["name"] for c in sa.inspect(engine).get_columns("profiles")}
