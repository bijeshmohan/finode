"""The budget flag goes once a person's books are in the four types: the upgrade refuses while Investments, Loans or a
group of one's own is left (convert the books first), and the downgrade brings the flags back as the types say."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from finode.config import settings

USER = "00000000-0000-4000-8000-0000000000aa"
BEFORE = "e8a0c2d4f6b9"
AFTER = "f9b1d3e5a7c0"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    command.upgrade(Config("alembic.ini"), BEFORE)
    yield Config("alembic.ini"), engine
    engine.dispose()


def _account(connection, key, name, parent=None, system_key=None, on_budget=0, starts=None):
    connection.execute(
        sa.text(
            "INSERT INTO accounts (id, user_id, name, parent_id, system_key, on_budget, new_accounts_in_budget, "
            "bill_rounding, pinned, created, updated) VALUES (:id, :u, :n, :p, :k, :b, :s, 'none', 0, "
            "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        ),
        {"id": key, "u": USER, "n": name, "p": parent, "k": system_key, "b": on_budget, "s": starts},
    )


def _books(engine, extra=None):
    ids = {
        name: f"00000000-0000-4000-8000-00000000{n:04x}"
        for n, name in enumerate(["Assets", "Liabilities", "Bank", "Card", "HDFC", "Amex", "Extra"], start=1)
    }
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        _account(connection, ids["Assets"], "Assets")
        _account(connection, ids["Liabilities"], "Liabilities")
        _account(connection, ids["Bank"], "Bank Account", ids["Assets"], "assets.bank", starts=1)
        _account(connection, ids["Card"], "Credit Card", ids["Liabilities"], "liabilities.cards", starts=1)
        _account(connection, ids["HDFC"], "HDFC", ids["Bank"], on_budget=1)
        _account(connection, ids["Amex"], "Amex", ids["Card"], on_budget=1)
        if extra:
            extra(connection, ids)
    return ids


def test_converted_books_lose_the_flag_and_get_it_back_on_downgrade(alembic):
    config, engine = alembic
    ids = _books(engine)
    command.upgrade(config, AFTER)
    columns = {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
    assert not {"on_budget", "new_accounts_in_budget"} & columns
    command.downgrade(config, BEFORE)
    with engine.connect() as connection:
        rows = dict(connection.execute(sa.text("SELECT id, on_budget FROM accounts")).all())
        starts = dict(connection.execute(sa.text("SELECT id, new_accounts_in_budget FROM accounts")).all())
    assert rows[ids["HDFC"]] and rows[ids["Amex"]] and not rows[ids["Assets"]]
    assert starts[ids["Bank"]] and starts[ids["HDFC"]] is None


@pytest.mark.parametrize(
    "left",
    [
        lambda c, ids: _account(c, ids["Extra"], "Loans", ids["Liabilities"], "liabilities.loans", starts=0),
        lambda c, ids: _account(c, ids["Extra"], "Wallets", ids["Assets"], starts=1),
        lambda c, ids: _account(c, ids["Extra"], "Loose", ids["Assets"], on_budget=1),
    ],
)
def test_unconverted_books_are_refused_and_nothing_changes(alembic, left):
    config, engine = alembic
    _books(engine, left)
    with pytest.raises(Exception, match="convert the books first"):
        command.upgrade(config, AFTER)
    assert "on_budget" in {c["name"] for c in sa.inspect(engine).get_columns("accounts")}
