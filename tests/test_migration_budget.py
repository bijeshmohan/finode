"""The budget migration switches on the asset accounts that hold a currency and nothing else."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.commodity_seed import seed_id
from app.config import settings


PARENT = "a3c5e7f9b124"
USER = uuid4()
NOW = datetime.now(timezone.utc)


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def test_asset_leaves_holding_a_currency_are_budgeted(alembic):
    config, engine = alembic
    command.upgrade(config, PARENT)
    assets, liabilities, bank, group, child, card, coins, expense_root, food = (uuid4() for _ in range(9))
    inr = seed_id("INR")
    rows = [
        (assets, "Assets", None, None), (liabilities, "Liabilities", None, None),
        (bank, "Bank", assets, inr), (group, "Group", assets, inr), (child, "Child", group, inr),
        (card, "Card", liabilities, inr), (expense_root, "Expenses", None, None), (food, "Food", expense_root, inr),
    ]
    with engine.begin() as c:
        for aid, name, parent, commodity in rows:
            c.execute(
                sa.text(
                    "INSERT INTO accounts (created, updated, aid, user, name, parent_id, commodity_id) "
                    "VALUES (:n, :n, :a, :u, :name, :p, :c)"
                ).bindparams(
                    sa.bindparam("a", aid, type_=sa.Uuid()),
                    sa.bindparam("u", USER, type_=sa.Uuid()),
                    sa.bindparam("p", parent, type_=sa.Uuid()),
                    sa.bindparam("c", commodity, type_=sa.Uuid()),
                    sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)),
                    sa.bindparam("name", name),
                )
            )

    command.upgrade(config, "head")

    with engine.connect() as c:
        flags = dict(c.execute(sa.text("SELECT name, on_budget FROM accounts")).all())
    assert {name for name, on in flags.items() if on} == {"Bank", "Child"}


def test_it_can_be_undone(alembic):
    config, engine = alembic
    command.upgrade(config, "head")
    command.downgrade(config, PARENT)
    with engine.connect() as c:
        inspector = sa.inspect(c)
        assert "budget_allocations" not in inspector.get_table_names()
        assert "on_budget" not in {col["name"] for col in inspector.get_columns("accounts")}
