"""The single-currency migration: every person keeps one currency, commodities and prices are gone, and it refuses
(changing nothing) when somebody recorded what a single currency cannot hold."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlmodel import SQLModel

from app.config import settings
from migrations.commodity_seed import seed_id

BEFORE = "e2a4c6e8f1b3"
NOW = datetime.now(UTC)
ASHA, BEN = uuid4(), uuid4()


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    config = Config("alembic.ini")
    engine = sa.create_engine(url)
    yield config, engine
    engine.dispose()


def _run(engine, sql, **values):
    binds = [
        sa.bindparam(
            k,
            v,
            type_=sa.Uuid() if isinstance(v, UUID) else sa.DateTime(timezone=True) if isinstance(v, datetime) else None,
        )
        for k, v in values.items()
    ]
    with engine.begin() as c:
        c.execute(
            sa.text(sql).bindparams(
                *binds,
                *(
                    []
                    if "n" in values
                    else [sa.bindparam("n", NOW, type_=sa.DateTime(timezone=True))]
                    if ":n" in sql
                    else []
                ),
            )
        )


def _ledger(engine, user, code="INR", amount="1234.56", worth=None, profile=True):
    """A bank account and a cash account, one transaction, in the currency `code`. Returns the transaction id."""
    root, bank, cash, tid = uuid4(), uuid4(), uuid4(), uuid4()
    cid = seed_id(code)
    _run(
        engine,
        "INSERT INTO accounts (created, updated, aid, user, name, parent_id, commodity_id) VALUES "
        "(:n, :n, :a, :u, 'Assets', NULL, NULL), (:n, :n, :b, :u, 'Bank', :a, :c), (:n, :n, :o, :u, 'Cash', :a, :c)",
        a=root,
        b=bank,
        o=cash,
        u=user,
        c=cid,
    )
    _run(
        engine,
        "INSERT INTO transactions (created, updated, tid, user, date, payee, currency_id, created_via) "
        "VALUES (:n, :n, :t, :u, '2026-01-02', 'x', :c, 'web')",
        t=tid,
        u=user,
        c=cid,
    )
    for account, side in ((bank, "DEBIT"), (cash, "CREDIT")):
        _run(
            engine,
            'INSERT INTO postings (created, updated, pid, user, "transaction", account, side, amount, value) '
            f"VALUES (:n, :n, :p, :u, :t, :a, :s, {amount}, {worth or amount})",
            p=uuid4(),
            u=user,
            t=tid,
            a=account,
            s=side,
        )
    if profile:
        _run(
            engine,
            "INSERT INTO profiles (created, updated, user, default_commodity_id) VALUES (:n, :n, :u, :c)",
            u=user,
            c=cid,
        )
    return tid


def _currency(engine, user):
    with engine.connect() as c:
        return c.execute(
            sa.text('SELECT currency FROM profiles WHERE "user" = :u').bindparams(
                sa.bindparam("u", user, type_=sa.Uuid())
            )
        ).scalar()


def test_the_schema_matches_the_models_and_commodities_are_gone(alembic):
    config, engine = alembic
    command.upgrade(config, "head")
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert "commodities" not in tables and "prices" not in tables
    for name, table in SQLModel.metadata.tables.items():
        if name == "auth.users":
            continue
        assert {c["name"] for c in inspector.get_columns(name)} == {c.name for c in table.columns}, name
    assert "value" not in {c["name"] for c in inspector.get_columns("postings")}
    profiles = {c["name"]: c for c in inspector.get_columns("profiles")}
    assert profiles["currency"]["nullable"] is False and "default_commodity_id" not in profiles


def test_everything_recorded_is_kept_and_the_currency_follows_the_profile(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    _tid = _ledger(engine, ASHA, "INR")
    _ledger(engine, BEN, "USD", amount="40.50")
    command.upgrade(config, "head")
    assert _currency(engine, ASHA) == "INR" and _currency(engine, BEN) == "USD"
    with engine.connect() as c:
        amounts = c.execute(sa.text("SELECT amount FROM postings ORDER BY amount")).scalars().all()
        assert [Decimal(str(a)) for a in amounts] == [
            Decimal("40.5"),
            Decimal("40.5"),
            Decimal("1234.56"),
            Decimal("1234.56"),
        ]
        assert c.execute(sa.text("SELECT count(*) FROM transactions")).scalar() == 2
        assert c.execute(sa.text("SELECT count(*) FROM accounts")).scalar() == 6


def test_someone_with_no_profile_yet_keeps_their_currency(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    _ledger(engine, BEN, "EUR", profile=False)
    _ledger(engine, ASHA, "INR", profile=False)
    command.upgrade(config, "head")
    assert _currency(engine, BEN) == "EUR", "a profile is made for them so the currency is not lost"
    assert _currency(engine, ASHA) is None, "the default (INR) applies without a row"


def test_a_profile_with_nothing_recorded_keeps_the_chosen_default(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    _run(
        engine,
        "INSERT INTO profiles (created, updated, user, default_commodity_id) VALUES (:n, :n, :u, :c)",
        u=ASHA,
        c=seed_id("GBP"),
    )
    _run(engine, "INSERT INTO profiles (created, updated, user) VALUES (:n, :n, :u)", u=BEN)
    command.upgrade(config, "head")
    assert _currency(engine, ASHA) == "GBP" and _currency(engine, BEN) == "INR"


def _refuses(alembic, setup, message):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    setup(engine)
    with pytest.raises(RuntimeError, match=message):
        command.upgrade(config, "head")
    with engine.connect() as c:
        assert c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == BEFORE, "nothing was changed"
        assert "commodities" in sa.inspect(c).get_table_names()


def test_assets_of_ones_own_stop_the_migration(alembic):
    _refuses(
        alembic,
        lambda e: _run(
            e,
            'INSERT INTO commodities (created, updated, cid, "user", code, name, kind, decimals) '
            "VALUES (:n, :n, :c, :u, 'BTC', 'Bitcoin', 'crypto', 8)",
            c=uuid4(),
            u=ASHA,
        ),
        "assets of their own",
    )


def test_prices_stop_the_migration(alembic):
    def setup(engine):
        _run(
            engine,
            "INSERT INTO prices (created, updated, pid, user, commodity_id, quote_id, date, price) "
            "VALUES (:n, :n, :p, :u, :a, :b, '2026-01-01', 83.5)",
            p=uuid4(),
            u=ASHA,
            a=seed_id("USD"),
            b=seed_id("INR"),
        )

    _refuses(alembic, setup, "prices were entered")


def test_a_ledger_in_two_currencies_stops_the_migration(alembic):
    def setup(engine):
        _ledger(engine, ASHA, "INR")
        _run(
            engine,
            "INSERT INTO accounts (created, updated, aid, user, name, parent_id, commodity_id) VALUES "
            "(:n, :n, :a, :u, 'Dollars', (SELECT aid FROM accounts LIMIT 1), :c)",
            a=uuid4(),
            u=ASHA,
            c=seed_id("USD"),
        )

    _refuses(alembic, setup, "more than one currency")


def test_a_conversion_stops_the_migration(alembic):
    _refuses(alembic, lambda e: _ledger(e, ASHA, "INR", amount="100", worth="8350"), "conversions between commodities")


def test_a_recurring_conversion_stops_the_migration(alembic):
    def setup(engine):
        _ledger(engine, ASHA, "INR")
        a, b = (
            UUID(str(x))
            for x in sa.create_engine(str(engine.url))
            .connect()
            .execute(sa.text("SELECT aid FROM accounts WHERE parent_id IS NOT NULL"))
            .scalars()
        )
        _run(
            engine,
            "INSERT INTO recurring_transactions (created, updated, rid, user, from_account, to_account, amount, received_amount, "
            "frequency, every, start_date, next_date, active) VALUES (:n, :n, :r, :u, :a, :b, 8350, 100, 'monthly', 1, "
            "'2026-01-01', '2026-02-01', 1)",
            r=uuid4(),
            u=ASHA,
            a=a,
            b=b,
        )

    _refuses(alembic, setup, "convert between commodities")


def test_the_migration_cannot_be_undone(alembic):
    config, _engine = alembic
    command.upgrade(config, "head")
    with pytest.raises(RuntimeError, match="cannot be undone"):
        command.downgrade(config, BEFORE)
