"""The migration that makes the books pure: the Income and Expenses accounts that only mirrored a category are gone,
their lines sit on the root with the category kept, a real books account survives, nothing the budget counts changes,
a change makes it refuse, and going back makes the mirror accounts again."""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.config import settings

from .test_migration_budget_categories import BEFORE, USER, account, entry, seed

PREVIOUS = "e4a6c8d0f2b3"
HEAD = "f5b7d9e1a3c4"


@pytest.fixture
def alembic(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migrate.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    engine = sa.create_engine(url)
    yield Config("alembic.ini"), engine
    engine.dispose()


def prepare(config, engine, extra=None):
    command.upgrade(config, BEFORE)
    with engine.begin() as conn:
        seed(conn)
    command.upgrade(config, "c7e9a1b3d5f8")
    if extra:
        with engine.begin() as conn:
            extra(conn)
    command.upgrade(config, PREVIOUS)


def test_lines_move_to_the_root_and_keep_their_category(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        names = {r.name for r in conn.execute(sa.text("SELECT name FROM accounts"))}
        assert names == {"Assets", "Liabilities", "Equity", "Income", "Expenses", "Bank", "Home loan"}
        lines = {
            (p.transaction[0], p.side): (p.account[0], p.category_id and p.category_id[0])
            for p in conn.execute(sa.text('SELECT "transaction", side, account, category_id FROM postings'))
        }
        assert lines[("1", "DEBIT")] == ("5", "d"), "groceries sit on Expenses, labelled Groceries"
        assert lines[("3", "CREDIT")] == ("4", "f"), "salary sits on Income, labelled Salary"
        assert lines[("2", "DEBIT")] == ("b", "e"), "the EMI stays on the loan with its category"
        rule = conn.execute(sa.text("SELECT account, category_id FROM recurring_postings")).one()
        assert (rule.account[0], rule.category_id[0]) == ("5", "d")
        assert (
            conn.execute(sa.text("SELECT payment_category_id FROM accounts WHERE name = 'Home loan'")).scalar()
            == "e" * 32
        )
        assert conn.execute(sa.text("SELECT count(*) FROM budget_categories")).scalar() == 5, "categories stay"


def test_a_real_books_account_inside_a_mirror_moves_up_to_the_root(alembic):
    config, engine = alembic

    def extra(conn):
        account(conn, "9", "Interest", parent="e")  # under EMI
        conn.execute(sa.text("UPDATE accounts SET category_id = :e WHERE aid = :a"), {"e": "e" * 32, "a": "9" * 32})

    prepare(config, engine, extra)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        row = conn.execute(sa.text("SELECT parent_id, category_id FROM accounts WHERE name = 'Interest'")).one()
        assert row.parent_id == "5" * 32 and row.category_id == "e" * 32


def test_an_entry_that_would_have_an_account_on_both_sides_is_refused(alembic):
    config, engine = alembic

    def extra(conn):
        entry(conn, "6", "2026-10-12", [("d", "DEBIT", 10), ("c", "CREDIT", 10)])  # Groceries to Food, both Expenses

    prepare(config, engine, extra)
    with pytest.raises(RuntimeError, match="nothing was changed"):
        command.upgrade(config, HEAD)
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM accounts WHERE name = 'Groceries'")).scalar() == 1


def test_going_back_makes_the_mirror_accounts_again(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    with engine.begin() as conn:
        mirrors = conn.execute(sa.text("SELECT name, parent_id FROM accounts WHERE category_id = aid")).all()
        assert {m.name for m in mirrors} == {"Food", "Groceries", "EMI", "Old", "Salary"}
        assert dict(mirrors)["Groceries"] == "c" * 32
        line = conn.execute(
            sa.text("SELECT account FROM postings WHERE \"transaction\" = :t AND side = 'DEBIT'"), {"t": "1" * 32}
        ).scalar()
        assert line == "d" * 32
