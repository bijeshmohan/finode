"""The ledger-integrity migration: existing transactions get a history, bad rows are refused."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.commodity_seed import seed_id
from app.config import settings


PARENT = "f1a3c5e7b892"
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


def _bind(**values):
    return [
        sa.bindparam(k, v, type_=sa.Uuid() if hasattr(v, "hex") else None)
        for k, v in values.items()
    ]


def _ledger(engine, amount="1234.56"):
    root, bank, cash, tid = uuid4(), uuid4(), uuid4(), uuid4()
    with engine.begin() as c:
        c.execute(
            sa.text(
                "INSERT INTO accounts (created, updated, aid, user, name, parent_id, commodity_id) VALUES "
                "(:n, :n, :a, :u, 'Assets', NULL, NULL), (:n, :n, :b, :u, 'Bank', :a, :c), (:n, :n, :o, :u, 'Cash', :a, :c)"
            ).bindparams(
                *_bind(a=root, b=bank, o=cash, u=USER, c=seed_id("INR")),
                sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)),
            )
        )
        c.execute(
            sa.text(
                "INSERT INTO transactions (created, updated, tid, user, date, payee, currency_id, created_via) "
                "VALUES (:n, :n, :t, :u, '2026-01-02', 'x', :c, 'web')"
            ).bindparams(
                *_bind(t=tid, u=USER, c=seed_id("INR")), sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True))
            )
        )
        for account, side in ((bank, "DEBIT"), (cash, "CREDIT")):
            c.execute(
                sa.text(
                    'INSERT INTO postings (created, updated, pid, user, "transaction", account, side, amount, value) '
                    f"VALUES (:n, :n, :p, :u, :t, :a, :s, {amount}, {amount})"
                ).bindparams(
                    *_bind(p=uuid4(), u=USER, t=tid, a=account),
                    sa.bindparam("s", side),
                    sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True)),
                )
            )
    return tid, bank


def test_existing_transactions_start_their_history(alembic):
    config, engine = alembic
    command.upgrade(config, PARENT)
    tid, bank = _ledger(engine)

    command.upgrade(config, "head")

    with engine.connect() as c:
        rows = c.execute(sa.text("SELECT action, via, snapshot FROM transaction_history")).all()
    assert len(rows) == 1 and rows[0][0] == "created" and rows[0][1] == "web"
    import json

    snapshot = json.loads(rows[0][2])
    assert snapshot["date"] == "2026-01-02" and snapshot["payee"] == "x"
    assert [(p["side"], p["amount"], p["value"]) for p in snapshot["postings"]] == [
        ("debit", "1234.56", "1234.56"),
        ("credit", "1234.56", "1234.56"),
    ] or sorted((p["side"], p["amount"]) for p in snapshot["postings"]) == [("credit", "1234.56"), ("debit", "1234.56")]


def test_the_database_refuses_postings_that_are_not_positive(alembic):
    config, engine = alembic
    command.upgrade(config, "head")
    tid, bank = _ledger(engine)
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as c:
        c.execute(sa.text("UPDATE postings SET amount = 0"))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as c:
        c.execute(sa.text("UPDATE postings SET value = -1"))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as c:
        c.execute(sa.text("UPDATE postings SET side = 'SIDEWAYS'"))


def test_migrating_stops_when_a_posting_is_already_wrong(alembic):
    config, engine = alembic
    command.upgrade(config, PARENT)
    _ledger(engine, amount="0")
    with pytest.raises(RuntimeError, match="not positive"):
        command.upgrade(config, "head")


def test_it_can_be_undone(alembic):
    config, engine = alembic
    command.upgrade(config, "head")
    command.downgrade(config, PARENT)
    with engine.connect() as c:
        assert "transaction_history" not in sa.inspect(c).get_table_names()
