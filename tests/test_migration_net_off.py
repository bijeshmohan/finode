"""The migration that lets an activity row be a net off widens one check; going back turns them into settlements."""

import pytest
import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "f1b3d5e7a9c6"
HEAD = "a3d5f7b9c1e4"

ROW = (
    "INSERT INTO party_transactions (created, id, user_id, contact_id, transaction_id, purpose, direction) "
    "VALUES ('2026-01-01', 'p1', :user, 'c1', :entry, 'netoff', 'received')"
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


def test_a_net_off_is_refused_before_and_accepted_after(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    with engine.begin() as conn:
        ids = start(conn)
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.execute(sa.text(ROW), ids)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        conn.execute(sa.text(ROW), ids)


def test_going_back_turns_net_offs_into_settlements(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    with engine.begin() as conn:
        conn.execute(sa.text(ROW), start(conn))
    command.downgrade(config, PREVIOUS)
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT purpose FROM party_transactions")).scalar() == "settlement"
