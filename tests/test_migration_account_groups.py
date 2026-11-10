"""The account-groups migration: the built-in groups keep the budget behaviour the code used to hold for them."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

BEFORE = "b4e6f8a0c2d5"
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


def _account(engine, name, key=None):
    with engine.begin() as c:
        c.execute(
            sa.text(
                "INSERT INTO accounts (created, updated, id, user_id, name, system_key) VALUES (:n, :n, :a, :u, :name, :k)"
            ).bindparams(
                sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)),
                sa.bindparam("a", uuid4(), type_=sa.Uuid()),
                sa.bindparam("u", USER, type_=sa.Uuid()),
                sa.bindparam("name", name),
                sa.bindparam("k", key),
            )
        )


def test_the_built_in_groups_get_their_choice_and_nothing_else_does(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    for name, key in (
        ("Bank Accounts", "assets.bank"),
        ("Cash", "assets.cash"),
        ("Investments", "assets.investments"),
        ("Credit Cards", "liabilities.cards"),
        ("Loans", "liabilities.loans"),
        ("HDFC", None),
    ):
        _account(engine, name, key)
    command.upgrade(config, "head")
    with engine.connect() as c:
        found = dict(c.execute(sa.text("SELECT name, new_accounts_in_budget FROM accounts")).all())
    assert found == {
        "Bank Accounts": 1,
        "Cash": 1,
        "Investments": 0,
        "Credit Cards": 1,
        "Loans": 0,
        "HDFC": None,
    }


def test_it_can_be_undone(alembic):
    config, engine = alembic
    command.upgrade(config, "head")
    command.downgrade(config, BEFORE)
    assert "new_accounts_in_budget" not in {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
    command.upgrade(config, "head")
