"""The payment-category migration adds the column and can be undone."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    yield Config("alembic.ini"), engine
    engine.dispose()


def test_upgrade_and_downgrade(alembic):
    config, engine = alembic
    command.upgrade(config, "e1a3c5d7f891")
    assert "payment_category_id" in {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
    command.downgrade(config, "d9f1b3c5e679")
    assert "payment_category_id" not in {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
