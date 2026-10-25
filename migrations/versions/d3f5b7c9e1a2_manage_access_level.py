"""A third access level for assistants: manage accounts

Revision ID: d3f5b7c9e1a2
Revises: c1e3a5b7d9f0
Create Date: 2026-10-25 14:00:00.000000

`api_tokens.scope` and `oauth_grants.scope` may now also be 'manage' (read, write and changing accounts). Nobody has
it until they choose it. Undoing this turns every 'manage' into 'write' first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3f5b7c9e1a2"
down_revision: str | Sequence[str] | None = "c1e3a5b7d9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (("api_tokens", "ck_api_tokens_scope"), ("oauth_grants", "ck_oauth_grants_scope"))


def _swap(allowed: str) -> None:
    for table, name in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="check")
            batch.create_check_constraint(name, sa.text(f"scope IN ({allowed})"))


def upgrade() -> None:
    _swap("'read', 'write', 'manage'")


def downgrade() -> None:
    for table, _ in TABLES:
        op.execute(sa.text(f"UPDATE {table} SET scope = 'write' WHERE scope = 'manage'"))
    _swap("'read', 'write'")
