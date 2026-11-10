"""The migration that lets an activity row be shared income widens two checks; going back turns them into advances."""

import pytest
import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "a3d5f7b9c1e4"
HEAD = "b4e6f8a0c2d5"

PARTY = (
    "INSERT INTO party_transactions (created, id, user_id, contact_id, transaction_id, purpose, direction) "
    "VALUES ('2026-01-01', 'p1', :user, 'c1', :entry, 'income', 'received')"
)
OBLIGATION = (
    "INSERT INTO party_obligations (created, id, user_id, contact_id, source_transaction_id, source_type, direction, "
    "original_amount) VALUES ('2026-01-01', 'o1', :user, 'c1', :entry, 'shared_income', 'payable', 5)"
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


def test_shared_income_is_refused_before_and_accepted_after(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    with engine.begin() as conn:
        ids = start(conn)
    for statement in (PARTY, OBLIGATION):
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(sa.text(statement), ids)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        conn.execute(sa.text(PARTY), ids)
        conn.execute(sa.text(OBLIGATION), ids)


def test_going_back_turns_them_into_advances(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        ids = start(conn)
        conn.execute(sa.text(PARTY), ids)
        conn.execute(sa.text(OBLIGATION), ids)
    command.downgrade(config, PREVIOUS)
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT purpose FROM party_transactions")).scalar() == "advance"
        assert conn.execute(sa.text("SELECT source_type FROM party_obligations")).scalar() == "advance"
