"""The category icons migration: every category gets the generic tag, the built-in Uncategorised its own mark."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from finode.config import settings

USER = "00000000-0000-4000-8000-0000000000aa"
BEFORE = "a1c3e5f7b9d2"
AFTER = "b2d4f6a8c0e1"
NOW = "2026-01-01 00:00:00"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    command.upgrade(Config("alembic.ini"), BEFORE)
    with engine.begin() as c:
        c.exec_driver_sql("PRAGMA foreign_keys=OFF")
        for n, name, key in ((1, "Groceries", None), (2, "Uncategorised", "uncategorised.spending")):
            c.execute(
                sa.text(
                    "INSERT INTO budget_categories (id, user_id, name, kind, system_key, created, updated) "
                    "VALUES (:id, :u, :n, 'spending', :k, :t, :t)"
                ),
                {"id": f"00000000-0000-4000-8000-{n:012x}", "u": USER, "n": name, "k": key, "t": NOW},
            )
    yield Config("alembic.ini"), engine
    engine.dispose()


def _icons(engine) -> dict[str, str]:
    with engine.connect() as c:
        return dict(c.execute(sa.text("SELECT name, icon FROM budget_categories")).all())


def test_existing_categories_get_tag_and_uncategorised_its_own(alembic):
    config, engine = alembic
    command.upgrade(config, AFTER)
    assert _icons(engine) == {"Groceries": "tag", "Uncategorised": "circle-dashed"}


def test_downgrade_and_up_again(alembic):
    config, engine = alembic
    command.upgrade(config, AFTER)
    command.downgrade(config, BEFORE)
    assert "icon" not in {c["name"] for c in sa.inspect(engine).get_columns("budget_categories")}
    command.upgrade(config, AFTER)
    assert _icons(engine)["Groceries"] == "tag"
