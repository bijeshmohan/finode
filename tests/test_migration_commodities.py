"""The commodities migration must keep every existing amount and balance exactly as it was."""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.commodity_seed import seed_id
from app.config import settings


PARENT = "9c2d4e6f1a51"
USER = uuid4()


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def _insert_ledger(engine) -> tuple[UUID, UUID, UUID]:
    now = datetime.now(timezone.utc)
    root, bank, tid = uuid4(), uuid4(), uuid4()
    other = uuid4()
    with engine.begin() as c:
        c.execute(
            sa.text(
                "INSERT INTO accounts (created, updated, aid, user, name, parent_id) VALUES "
                "(:n, :n, :a, :u, 'Assets', NULL), (:n, :n, :b, :u, 'Bank', :a), (:n, :n, :o, :u, 'Cash', :a)"
            ).bindparams(
                sa.bindparam("a", root, type_=sa.Uuid()),
                sa.bindparam("b", bank, type_=sa.Uuid()),
                sa.bindparam("o", other, type_=sa.Uuid()),
                sa.bindparam("u", USER, type_=sa.Uuid()),
                sa.bindparam("n", now, type_=sa.DateTime(timezone=True)),
            )
        )
        c.execute(
            sa.text(
                "INSERT INTO transactions (created, updated, tid, user, date, payee) VALUES (:n, :n, :t, :u, '2026-01-02', 'x')"
            ).bindparams(
                sa.bindparam("t", tid, type_=sa.Uuid()),
                sa.bindparam("u", USER, type_=sa.Uuid()),
                sa.bindparam("n", now, type_=sa.DateTime(timezone=True)),
            )
        )
        for account, side in ((bank, "DEBIT"), (other, "CREDIT")):
            c.execute(
                sa.text(
                    "INSERT INTO postings (created, updated, pid, user, \"transaction\", account, side, amount) "
                    "VALUES (:n, :n, :p, :u, :t, :a, :s, 1234.56)"
                ).bindparams(
                    sa.bindparam("p", uuid4(), type_=sa.Uuid()),
                    sa.bindparam("u", USER, type_=sa.Uuid()),
                    sa.bindparam("t", tid, type_=sa.Uuid()),
                    sa.bindparam("a", account, type_=sa.Uuid()),
                    sa.bindparam("s", side),
                    sa.bindparam("n", now, type_=sa.DateTime(timezone=True)),
                )
            )
        c.execute(
            sa.text(
                "INSERT INTO profiles (created, updated, user, first_name) VALUES (:n, :n, :u, 'Asha')"
            ).bindparams(
                sa.bindparam("u", USER, type_=sa.Uuid()), sa.bindparam("n", now, type_=sa.DateTime(timezone=True))
            )
        )
    return root, bank, tid


def test_existing_data_is_backfilled_in_the_default_currency(alembic):
    config, engine = alembic
    command.upgrade(config, PARENT)
    root, bank, tid = _insert_ledger(engine)

    command.upgrade(config, "head")

    inr = seed_id("INR")
    with engine.connect() as c:
        commodities = {code for (code,) in c.execute(sa.text("SELECT code FROM commodities"))}
        assert {"INR", "USD", "BTC"} <= commodities
        accounts = {
            name: commodity
            for name, commodity in c.execute(sa.text("SELECT name, commodity_id FROM accounts"))
        }
        assert accounts["Assets"] is None, "root accounts hold nothing of their own"
        assert UUID(accounts["Bank"]) == inr and UUID(accounts["Cash"]) == inr
        (currency,) = c.execute(sa.text("SELECT currency_id FROM transactions")).one()
        assert UUID(currency) == inr
        (default,) = c.execute(sa.text("SELECT default_commodity_id FROM profiles")).one()
        assert UUID(default) == inr
        rows = c.execute(sa.text("SELECT amount, value FROM postings")).all()
        assert [(Decimal(str(a)), Decimal(str(v))) for a, v in rows] == [(Decimal("1234.56"),) * 2] * 2


def test_upgrade_downgrade_upgrade_is_clean(alembic):
    config, engine = alembic
    command.upgrade(config, "head")
    command.downgrade(config, PARENT)
    with engine.connect() as c:
        tables = set(sa.inspect(c).get_table_names())
        assert "commodities" not in tables
        assert "value" not in {col["name"] for col in sa.inspect(c).get_columns("postings")}
    command.upgrade(config, "head")
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT count(*) FROM commodities")).scalar() > 0


def test_downgrade_keeps_the_amounts(alembic):
    config, engine = alembic
    command.upgrade(config, PARENT)
    _insert_ledger(engine)
    command.upgrade(config, "head")
    command.downgrade(config, PARENT)
    with engine.connect() as c:
        amounts = [Decimal(str(a)) for (a,) in c.execute(sa.text("SELECT amount FROM postings"))]
    assert amounts == [Decimal("1234.56")] * 2


def test_migrated_schema_has_the_columns_the_models_declare(alembic):
    from sqlmodel import SQLModel

    config, engine = alembic
    command.upgrade(config, "head")
    inspector = sa.inspect(engine)
    for table in ("commodities", "accounts", "transactions", "postings", "profiles"):
        declared = {c.name for c in SQLModel.metadata.tables[table].columns}
        migrated = {c["name"] for c in inspector.get_columns(table)}
        assert declared == migrated, table
    indexes = {i["name"] for i in inspector.get_indexes("commodities")}
    assert {"uq_commodities_global_code", "uq_commodities_user_code"} <= indexes
