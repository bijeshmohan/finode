"""The migration that removes Build and Earn: the flags go, and so do the plan rows of everything that is not an expense
category; the ledger and the expense categories' plan stay as they were."""

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


def account(conn, key, name, parent=None, saving=0):
    conn.execute(
        sa.text('INSERT INTO accounts (aid, "user", name, parent_id, on_budget, saving, created, updated) VALUES (:a, :u, :n, :p, 0, :s, :t, :t)'),
        {"a": key * 32, "u": USER, "n": name, "p": parent * 32 if parent else None, "s": saving, "t": NOW},
    )


def plan(conn, key, account_key, amount="100"):
    conn.execute(
        sa.text('INSERT INTO budget_allocations (bid, "user", month, account_id, amount, created, updated) VALUES (:b, :u, :m, :a, :x, :t, :t)'),
        {"b": key * 32, "u": USER, "m": "2026-10-01", "a": account_key * 32, "x": amount, "t": NOW},
    )


def test_only_the_expense_plan_is_kept_and_the_flags_go(alembic):
    config, engine = alembic
    command.upgrade(config, "b9d1f3a5c7e2")
    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
        for key, name in (("1", "Assets"), ("2", "Expenses"), ("3", "Income"), ("4", "Liabilities")):
            account(conn, key, name)
        account(conn, "5", "Food", parent="2")
        account(conn, "6", "Groceries", parent="5")
        account(conn, "7", "Mutual Funds", parent="1", saving=1)
        account(conn, "8", "Home Loan", parent="4", saving=1)
        account(conn, "9", "Salary", parent="3")
        for key, target in (("a", "5"), ("b", "6"), ("c", "7"), ("d", "8"), ("e", "9")):
            plan(conn, key, target)
        for key, target in (("f", "6"), ("g", "7")):
            conn.execute(
                sa.text('INSERT INTO budget_targets (tgid, "user", account_id, kind, amount, created, updated) VALUES (:t, :u, :a, \'monthly\', 5, :n, :n)'),
                {"t": key * 32, "u": USER, "a": target * 32, "n": NOW},
            )
        conn.execute(sa.text('INSERT INTO profiles ("user", currency, advanced, plan_build, plan_earn, created, updated) VALUES (:u, \'INR\', 1, 1, 1, :t, :t)'), {"u": USER, "t": NOW})
    command.upgrade(config, "c4e6a8b0d2f4")
    with engine.begin() as conn:
        assert sorted(conn.execute(sa.text("SELECT account_id FROM budget_allocations")).scalars()) == ["5" * 32, "6" * 32]
        assert conn.execute(sa.text("SELECT account_id FROM budget_targets")).scalars().all() == ["6" * 32]
        assert conn.execute(sa.text("SELECT count(*) FROM accounts")).scalar() == 9, "no account is touched"
    inspector = sa.inspect(engine)
    assert "saving" not in {c["name"] for c in inspector.get_columns("accounts")}
    assert not {"plan_build", "plan_earn"} & {c["name"] for c in inspector.get_columns("profiles")}
    command.downgrade(config, "b9d1f3a5c7e2")
    inspector = sa.inspect(engine)
    assert "saving" in {c["name"] for c in inspector.get_columns("accounts")}
    assert {"plan_build", "plan_earn"} <= {c["name"] for c in inspector.get_columns("profiles")}
