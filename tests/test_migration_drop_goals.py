"""The migration that removes goals drops both tables and can be undone (empty tables come back, the plan stays)."""

import sqlalchemy as sa
from alembic import command

from .test_migration_pure_books import alembic, prepare  # noqa: F401  (the fixture is used by name)

PREVIOUS = "e1a3c5b7d9f2"
HEAD = "a6c8e0b2d4f1"


def test_upgrade_drops_the_tables_and_the_plan_stays(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, PREVIOUS)
    assert {"goals", "goal_allocations"} <= set(sa.inspect(engine).get_table_names())
    with engine.begin() as conn:
        plan = conn.execute(sa.text("SELECT count(*) FROM budget_allocations")).scalar()
    command.upgrade(config, HEAD)
    assert not {"goals", "goal_allocations"} & set(sa.inspect(engine).get_table_names())
    with engine.begin() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM budget_allocations")).scalar() == plan


def test_downgrade_brings_back_empty_tables(alembic):
    config, engine = alembic
    prepare(config, engine)
    command.upgrade(config, HEAD)
    command.downgrade(config, PREVIOUS)
    inspector = sa.inspect(engine)
    assert {c["name"] for c in inspector.get_columns("goals")} >= {"id", "user_id", "name", "amount", "target_date"}
    assert {c["name"] for c in inspector.get_columns("goal_allocations")} >= {
        "id",
        "user_id",
        "month",
        "goal_id",
        "amount",
    }
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM goals")).scalar() == 0
