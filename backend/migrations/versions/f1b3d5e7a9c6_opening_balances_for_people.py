"""Contacts: opening balances (what a person already owed before finode)

Revision ID: f1b3d5e7a9c6
Revises: e0a2c4d6f8b5
Create Date: 2026-11-07 12:00:00.000000

An opening balance is an obligation whose source is `opening` and an activity row whose purpose is `opening`: the two
CHECKs learn the new word. Downgrading turns them back into a loan (they owed you) or a borrowing (you owed them).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b3d5e7a9c6"
down_revision: str | Sequence[str] | None = "e0a2c4d6f8b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES = "'loan', 'borrowing', 'advance', 'gift', 'expense', 'settlement'"
SOURCES = "'shared_expense', 'loan', 'borrowing', 'advance'"


def _checks(purposes: str, sources: str) -> None:
    with op.batch_alter_table("party_transactions") as batch:
        batch.drop_constraint("ck_party_transactions_purpose", type_="check")
        batch.create_check_constraint("ck_party_transactions_purpose", f"purpose IN ({purposes})")
    with op.batch_alter_table("party_obligations") as batch:
        batch.drop_constraint("ck_party_obligations_source", type_="check")
        batch.create_check_constraint("ck_party_obligations_source", f"source_type IN ({sources})")


def upgrade() -> None:
    _checks(f"{PURPOSES}, 'opening'", f"{SOURCES}, 'opening'")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE party_obligations SET source_type = CASE direction WHEN 'receivable' THEN 'loan' ELSE 'borrowing' END "
            "WHERE source_type = 'opening'"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE party_transactions SET purpose = CASE direction WHEN 'sent' THEN 'loan' ELSE 'borrowing' END "
            "WHERE purpose = 'opening'"
        )
    )
    _checks(PURPOSES, SOURCES)
