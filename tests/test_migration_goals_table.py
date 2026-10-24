"""The migration that gives goals their own tables: an old goal (an Expenses category with a by-date target and nothing
inside it) moves across with what was set aside and its category goes; one that has an entry or is used elsewhere stays
an ordinary category; nothing else is touched."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

USER = "00000000-0000-4000-8000-000000000001"
NOW = "2026-10-01"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    yield Config("alembic.ini"), engine
    engine.dispose()


def account(conn, key, name, parent=None):
    conn.execute(
        sa.text(
            'INSERT INTO accounts (aid, "user", name, parent_id, on_budget, created, updated) VALUES (:a, :u, :n, :p, 0, :t, :t)'
        ),
        {"a": key * 32, "u": USER, "n": name, "p": parent * 32 if parent else None, "t": NOW},
    )


def plan(conn, key, account_key, month, amount):
    conn.execute(
        sa.text(
            'INSERT INTO budget_allocations (bid, "user", month, account_id, amount, created, updated) VALUES (:b, :u, :m, :a, :x, :t, :t)'
        ),
        {"b": key * 32, "u": USER, "m": month, "a": account_key * 32, "x": amount, "t": NOW},
    )


def target(conn, key, account_key, kind, amount, date=None):
    conn.execute(
        sa.text(
            'INSERT INTO budget_targets (tgid, "user", account_id, kind, amount, target_date, created, updated) VALUES (:t, :u, :a, :k, :x, :d, :n, :n)'
        ),
        {"t": key * 32, "u": USER, "a": account_key * 32, "k": kind, "x": amount, "d": date, "n": NOW},
    )


def seed(conn):
    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    for key, name in (("1", "Assets"), ("2", "Expenses")):
        account(conn, key, name)
    account(conn, "3", "Goa trip", parent="2")
    account(conn, "4", "Bike", parent="2")
    account(conn, "5", "Rent", parent="2")
    account(conn, "6", "Bank", parent="1")
    plan(conn, "a", "3", "2026-09-01", "1000")
    plan(conn, "b", "3", "2026-10-01", "2000")
    plan(conn, "c", "4", "2026-10-01", "500")
    plan(conn, "d", "5", "2026-10-01", "700")
    target(conn, "e", "3", "by_date", "50000", "2027-03-01")
    target(conn, "f", "4", "by_date", "9000", "2027-03-01")
    target(conn, "g", "5", "monthly", "700")
    conn.execute(
        sa.text('INSERT INTO transactions (tid, "user", date, created, updated) VALUES (:t, :u, :d, :n, :n)'),
        {"t": "9" * 32, "u": USER, "d": NOW, "n": NOW},
    )
    for key, acct, side in (("h", "4", "DEBIT"), ("i", "6", "CREDIT")):
        conn.execute(
            sa.text(
                'INSERT INTO postings (pid, "user", "transaction", account, side, amount, created, updated) VALUES (:p, :u, :t, :a, :s, 100, :n, :n)'
            ),
            {"p": key * 32, "u": USER, "t": "9" * 32, "a": acct * 32, "s": side, "n": NOW},
        )


def test_goals_move_across_and_the_rest_stays(alembic):
    config, engine = alembic
    command.upgrade(config, "c4e6a8b0d2f4")
    with engine.begin() as conn:
        seed(conn)
    command.upgrade(config, "d5f7a9c1e3b4")
    with engine.begin() as conn:
        goals = conn.execute(sa.text("SELECT name, amount, target_date FROM goals")).all()
        assert [(g.name, float(g.amount), g.target_date) for g in goals] == [("Goa trip", 50000.0, "2027-03-01")]
        rows = conn.execute(sa.text("SELECT month, amount FROM goal_allocations ORDER BY month")).all()
        assert [(r.month, float(r.amount)) for r in rows] == [("2026-09-01", 1000.0), ("2026-10-01", 2000.0)]
        names = set(conn.execute(sa.text("SELECT name FROM accounts")).scalars())
        assert names == {"Assets", "Expenses", "Bike", "Rent", "Bank"}, (
            "the unused goal's category goes, the others stay"
        )
        assert sorted(conn.execute(sa.text("SELECT account_id FROM budget_allocations")).scalars()) == [
            "4" * 32,
            "5" * 32,
        ]
        assert sorted(conn.execute(sa.text("SELECT account_id FROM budget_targets")).scalars()) == ["4" * 32, "5" * 32]
        assert conn.execute(sa.text("SELECT count(*) FROM postings")).scalar() == 2, "the ledger is untouched"


def test_going_back_is_refused_while_goals_exist_and_works_when_there_are_none(alembic):
    config, engine = alembic
    command.upgrade(config, "c4e6a8b0d2f4")
    with engine.begin() as conn:
        seed(conn)
    command.upgrade(config, "d5f7a9c1e3b4")
    with pytest.raises(RuntimeError):
        command.downgrade(config, "c4e6a8b0d2f4")
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM goal_allocations"))
        conn.execute(sa.text("DELETE FROM goals"))
    command.downgrade(config, "c4e6a8b0d2f4")
    assert not {"goals", "goal_allocations"} & set(sa.inspect(engine).get_table_names())
