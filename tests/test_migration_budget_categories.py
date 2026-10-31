"""The migration that gives the budget its own categories: every Income and Expenses account becomes a category with the
same id, every line carries its account's category, a payment into a lender carries its payment category, nothing the
budget counts changes, and a mismatch makes it refuse."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

USER = "00000000-0000-4000-8000-000000000001"
NOW = "2026-10-01"
BEFORE = "b3d5f7a9c1e2"
AFTER = "c7e9a1b3d5f8"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    yield Config("alembic.ini"), engine
    engine.dispose()


def account(conn, key, name, parent=None, on_budget=0, pay=None, closed=None):
    conn.execute(
        sa.text(
            'INSERT INTO accounts (aid, "user", name, parent_id, on_budget, payment_category_id, closed_on, details, '
            "created, updated) VALUES (:a, :u, :n, :p, :b, :c, :x, :d, :t, :t)"
        ),
        {
            "a": key * 32,
            "u": USER,
            "n": name,
            "p": parent * 32 if parent else None,
            "b": on_budget,
            "c": pay * 32 if pay else None,
            "x": closed,
            "d": f"about {name}",
            "t": NOW,
        },
    )


def entry(conn, key, day, lines):
    conn.execute(
        sa.text('INSERT INTO transactions (tid, "user", date, created, updated) VALUES (:t, :u, :d, :n, :n)'),
        {"t": key * 32, "u": USER, "d": day, "n": NOW},
    )
    for i, (acct, side, amount) in enumerate(lines):
        conn.execute(
            sa.text(
                'INSERT INTO postings (pid, "user", "transaction", account, side, amount, created, updated) '
                "VALUES (:p, :u, :t, :a, :s, :x, :n, :n)"
            ),
            {
                "p": f"{key}{i}".ljust(32, "0"),
                "u": USER,
                "t": key * 32,
                "a": acct * 32,
                "s": side,
                "x": amount,
                "n": NOW,
            },
        )


def seed(conn):
    conn.execute(sa.text("PRAGMA foreign_keys=OFF"))
    for key, name in (("1", "Assets"), ("2", "Liabilities"), ("3", "Equity"), ("4", "Income"), ("5", "Expenses")):
        account(conn, key, name)
    account(conn, "a", "Bank", parent="1", on_budget=1)
    account(conn, "b", "Home loan", parent="2")  # a loan outside the budget
    account(conn, "c", "Food", parent="5")
    account(conn, "d", "Groceries", parent="c")
    account(conn, "e", "EMI", parent="5")
    account(conn, "f", "Salary", parent="4")
    account(conn, "6", "Old", parent="5", closed="2026-09-30")
    conn.execute(sa.text("UPDATE accounts SET payment_category_id = :e WHERE aid = :b"), {"e": "e" * 32, "b": "b" * 32})
    conn.execute(
        sa.text(
            'INSERT INTO budget_allocations (bid, "user", month, account_id, amount, created, updated) '
            "VALUES (:b, :u, '2026-10-01', :a, 5000, :t, :t)"
        ),
        {"b": "9" * 32, "u": USER, "a": "d" * 32, "t": NOW},
    )
    entry(conn, "1", "2026-10-03", [("d", "DEBIT", 400), ("a", "CREDIT", 400)])  # groceries from the bank
    entry(conn, "2", "2026-10-05", [("b", "DEBIT", 1000), ("a", "CREDIT", 1000)])  # EMI paid into the loan
    entry(conn, "3", "2026-10-07", [("a", "DEBIT", 9000), ("f", "CREDIT", 9000)])  # salary
    entry(conn, "4", "2026-10-09", [("d", "CREDIT", 50), ("a", "DEBIT", 50)])  # a refund
    entry(conn, "5", "2026-10-11", [("b", "CREDIT", 7000), ("a", "DEBIT", 7000)])  # the loan pays out: no category
    conn.execute(
        sa.text(
            'INSERT INTO recurring_transactions (rid, "user", from_account, to_account, amount, frequency, every, '
            "start_date, next_date, active, tags, created, updated) VALUES "
            "(:r, :u, :f, :t, 1000, 'monthly', 1, '2026-10-05', '2026-11-05', 1, '[]', :n, :n)"
        ),
        {"r": "8" * 32, "u": USER, "f": "a" * 32, "t": "b" * 32, "n": NOW},
    )
    conn.execute(
        sa.text(
            'INSERT INTO recurring_postings (rpid, "user", rid, account, side, amount, position, created, updated) '
            "VALUES (:p, :u, :r, :a, 'debit', 5, 0, :n, :n)"
        ),
        {"p": "7" * 32, "u": USER, "r": "8" * 32, "a": "d" * 32, "n": NOW},
    )


def test_categories_are_made_from_the_accounts_and_the_lines_follow(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    with engine.begin() as conn:
        seed(conn)
    command.upgrade(config, AFTER)
    with engine.begin() as conn:
        cats = {
            c.bcid: c
            for c in conn.execute(
                sa.text("SELECT bcid, name, kind, parent_id, details, closed_on FROM budget_categories")
            )
        }
        assert {c.name: c.kind for c in cats.values()} == {
            "Food": "spending",
            "Groceries": "spending",
            "EMI": "spending",
            "Old": "spending",
            "Salary": "earning",
        }, "roots, assets and liabilities are not categories"
        by_name = {c.name: c for c in cats.values()}
        assert by_name["Groceries"].bcid == "d" * 32, "a category keeps its account's id"
        assert by_name["Groceries"].parent_id == "c" * 32
        assert by_name["Food"].parent_id is None, "directly under a root means no group"
        assert by_name["Groceries"].details == "about Groceries"
        assert by_name["Old"].closed_on == "2026-09-30"
        marks = dict(conn.execute(sa.text("SELECT name, category_id FROM accounts")).all())
        assert marks["Groceries"] == "d" * 32 and marks["Bank"] is None and marks["Expenses"] is None
        lines = {
            (p.transaction[0], p.account[0]): p.category_id
            for p in conn.execute(sa.text('SELECT "transaction", account, category_id FROM postings'))
        }
        assert lines[("1", "d")] == "d" * 32, "a line to a category's account carries it"
        assert lines[("1", "a")] is None
        assert lines[("2", "b")] == "e" * 32, "a payment into a lender carries its payment category"
        assert lines[("5", "b")] is None, "the loan paying out is not spending"
        assert lines[("3", "f")] == "f" * 32
        assert conn.execute(sa.text("SELECT category_id FROM budget_allocations")).scalar() == "d" * 32
        assert conn.execute(sa.text("SELECT category_id FROM recurring_transactions")).scalar() == "e" * 32
        assert conn.execute(sa.text("SELECT category_id FROM recurring_postings")).scalar() == "d" * 32
        assert conn.execute(sa.text("SELECT count(*) FROM postings")).scalar() == 10, "the ledger is untouched"


def test_the_check_refuses_when_a_line_loses_its_category(alembic):
    import importlib.util
    from pathlib import Path

    config, engine = alembic
    command.upgrade(config, BEFORE)
    with engine.begin() as conn:
        seed(conn)
    command.upgrade(config, AFTER)
    path = Path("migrations/versions/c7e9a1b3d5f8_budget_categories.py")
    spec = importlib.util.spec_from_file_location("budget_categories_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        migration.check(conn)  # as migrated, the two rules agree
        conn.execute(sa.text("UPDATE postings SET category_id = NULL WHERE account = :a"), {"a": "b" * 32})
        with pytest.raises(RuntimeError, match="would change"):
            migration.check(conn)


def test_going_back_removes_the_new_columns_and_table(alembic):
    config, engine = alembic
    command.upgrade(config, BEFORE)
    with engine.begin() as conn:
        seed(conn)
    command.upgrade(config, AFTER)
    command.downgrade(config, BEFORE)
    inspector = sa.inspect(engine)
    assert "budget_categories" not in inspector.get_table_names()
    for table in ("accounts", "postings", "budget_allocations", "recurring_transactions", "recurring_postings"):
        assert "category_id" not in {c["name"] for c in inspector.get_columns(table)}
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM postings")).scalar() == 10
