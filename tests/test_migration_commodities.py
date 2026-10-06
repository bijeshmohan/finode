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
        assert {"INR", "USD", "TRY", "KWD"} <= commodities
        assert "BTC" not in commodities, "no shared non-currency rows remain"
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
        assert "commodities" not in tables and "prices" not in tables
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
    for table in ("commodities", "prices", "accounts", "transactions", "postings", "profiles", "api_tokens", "oauth_grants", "recurring_transactions"):
        declared = {c.name for c in SQLModel.metadata.tables[table].columns}
        migrated = {c["name"] for c in inspector.get_columns(table)}
        assert declared == migrated, table
    indexes = {i["name"] for i in inspector.get_indexes("commodities")}
    assert {"uq_commodities_global_code", "uq_commodities_user_code"} <= indexes
    price_indexes = {i["name"] for i in inspector.get_indexes("prices")}
    assert "uq_prices_user" in price_indexes and "uq_prices_global" not in price_indexes
    assert not {c["name"]: c for c in inspector.get_columns("prices")}["user"]["nullable"]


# ---- the "own assets only" revision --------------------------------------------------------------------------------

PRIOR = "b2e4a6c8d013"


OLD_CURRENCIES = (
    "INR USD EUR GBP JPY AUD CAD CHF CNY HKD SGD AED SAR NZD SEK NOK DKK ZAR".split()
)


def _as_before(engine):
    """Put the shared catalog back the way it was when the revision before this one ran."""
    with engine.begin() as c:
        c.execute(
            sa.text('DELETE FROM commodities WHERE "user" IS NULL AND code NOT IN :keep').bindparams(
                sa.bindparam("keep", OLD_CURRENCIES, expanding=True)
            )
        )
    for code, name, decimals in (("BTC", "Bitcoin", 8), ("ETH", "Ether", 8)):
        _insert(
            engine,
            'INSERT INTO commodities (created, updated, cid, "user", code, name, kind, decimals) '
            "VALUES (:n, :n, :c, NULL, :code, :name, 'crypto', :d)",
            c=uuid4(), code=code, name=name, d=decimals,
        )


def _ids(engine):
    with engine.connect() as c:
        return {code: UUID(str(cid)) for cid, code in c.execute(sa.text('SELECT cid, code FROM commodities WHERE "user" IS NULL'))}


def _insert(engine, sql, **params):
    types = {k: sa.Uuid() for k, v in params.items() if isinstance(v, UUID)}
    now = datetime.now(timezone.utc)
    with engine.begin() as c:
        c.execute(
            sa.text(sql).bindparams(
                *[sa.bindparam(k, v, type_=types.get(k)) for k, v in params.items()],
                *([sa.bindparam("n", now, type_=sa.DateTime(timezone=True))] if ":n" in sql else []),
            )
        )


def test_shared_coins_in_use_become_the_users_own(alembic):
    config, engine = alembic
    command.upgrade(config, PARENT)
    root, bank, tid = _insert_ledger(engine)
    command.upgrade(config, PRIOR)
    _as_before(engine)
    ids = _ids(engine)
    assert "BTC" in ids and "ETH" in ids
    _insert(engine, "UPDATE accounts SET commodity_id = :b WHERE aid = :a", b=ids["BTC"], a=bank)
    _insert(
        engine,
        'INSERT INTO prices (created, updated, pid, "user", commodity_id, quote_id, date, price) '
        "VALUES (:n, :n, :p, :u, :b, :i, '2026-01-02', 5000000)",
        p=uuid4(), u=USER, b=ids["BTC"], i=ids["INR"],
    )
    _insert(
        engine,
        'INSERT INTO prices (created, updated, pid, "user", commodity_id, quote_id, date, price) '
        "VALUES (:n, :n, :p, NULL, :e, :i, '2026-01-02', 200000)",
        p=uuid4(), e=ids["ETH"], i=ids["INR"],
    )

    command.upgrade(config, "head")

    with engine.connect() as c:
        shared = {code for (code,) in c.execute(sa.text('SELECT code FROM commodities WHERE "user" IS NULL AND kind <> \'currency\''))}
        assert shared == set(), "the shared coins are gone"
        (own,) = c.execute(sa.text('SELECT cid, code, kind, decimals FROM commodities WHERE "user" IS NOT NULL')).all()
        assert own[1:] == ("BTC", "crypto", 8)
        (held,) = c.execute(sa.text("SELECT commodity_id FROM accounts WHERE aid = :a").bindparams(sa.bindparam("a", bank, type_=sa.Uuid()))).one()
        assert UUID(held) == UUID(own[0]), "the account holds the user's copy"
        prices = c.execute(sa.text("SELECT commodity_id FROM prices")).all()
        assert [UUID(p[0]) for p in prices] == [UUID(own[0])], "the user's price follows; the shared feed is dropped"


def test_the_full_iso_list_is_present_and_old_ids_are_kept(alembic):
    config, engine = alembic
    command.upgrade(config, PRIOR)
    _as_before(engine)
    before = _ids(engine)
    command.upgrade(config, "head")
    after = _ids(engine)
    assert len(after) > 150 and {"TRY", "KWD", "VND"} <= set(after)
    assert all(after[code] == cid for code, cid in before.items() if code in after), "existing currency ids are unchanged"


def test_a_clashing_private_code_stops_the_upgrade_with_a_clear_message(alembic):
    config, engine = alembic
    command.upgrade(config, PRIOR)
    _as_before(engine)
    _insert(
        engine,
        'INSERT INTO commodities (created, updated, cid, "user", code, name, kind, decimals) '
        "VALUES (:n, :n, :c, :u, 'TRY', 'Some stock', 'stock', 2)",
        c=uuid4(), u=USER,
    )
    with pytest.raises(RuntimeError, match="TRY"):
        command.upgrade(config, "head")


def test_downgrade_restores_the_feed_shape(alembic):
    config, engine = alembic
    command.upgrade(config, "head")
    command.downgrade(config, PRIOR)
    inspector = sa.inspect(engine)
    assert {i["name"] for i in inspector.get_indexes("prices")} >= {"uq_prices_global", "uq_prices_user"}
    assert {c["name"]: c for c in inspector.get_columns("prices")}["user"]["nullable"]
