"""The migration that lets a person have an opening balance widens two checks; going back turns opening balances into a
loan (they owed you) or a borrowing (you owed them)."""

import pytest
import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "e0a2c4d6f8b5"
HEAD = "f1b3d5e7a9c6"

PARTY = (
    "INSERT INTO party_transactions (created, id, user_id, contact_id, transaction_id, purpose, direction) "
    "VALUES ('2026-01-01', :id, :user, 'c1', :entry, 'opening', :direction)"
)
OWED = (
    "INSERT INTO party_obligations (created, id, user_id, contact_id, source_transaction_id, source_type, "
    "direction, original_amount) VALUES ('2026-01-01', :id, :user, 'c1', :entry, 'opening', :direction, 5)"
)


def start(conn):
    user = conn.execute(sa.text("SELECT user_id FROM accounts LIMIT 1")).scalar()
    entry = conn.execute(sa.text("SELECT id FROM transactions LIMIT 1")).scalar()
    conn.execute(
        sa.text(
            "INSERT INTO contacts (created, updated, id, user_id, name) VALUES ('2026-01-01', '2026-01-01', 'c1', :u, 'A')"
        ),
        {"u": user},
    )
    return {"user": user, "entry": entry}


def test_opening_is_refused_before_and_accepted_after(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    with engine.begin() as conn:
        ids = start(conn)
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(sa.text(PARTY), {**ids, "id": "p1", "direction": "sent"})
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        conn.execute(sa.text(PARTY), {**ids, "id": "p1", "direction": "sent"})
        conn.execute(sa.text(OWED), {**ids, "id": "o1", "direction": "receivable"})


def test_going_back_turns_opening_balances_into_loans_and_borrowings(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        ids = start(conn)
        conn.execute(sa.text(PARTY), {**ids, "id": "p1", "direction": "sent"})
        conn.execute(sa.text(OWED), {**ids, "id": "o1", "direction": "receivable"})
        conn.execute(sa.text(OWED), {**ids, "id": "o2", "direction": "payable"})
    command.downgrade(config, PREVIOUS)
    with engine.begin() as conn:
        kinds = dict(conn.execute(sa.text("SELECT id, source_type FROM party_obligations")).all())
        assert kinds == {"o1": "loan", "o2": "borrowing"}
        assert conn.execute(sa.text("SELECT purpose FROM party_transactions")).scalar() == "loan"
