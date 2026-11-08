"""Contacts: income shared with people

Revision ID: b4e6f8a0c2d5
Revises: a3d5f7b9c1e4
Create Date: 2026-11-08 18:00:00.000000

Income shared with people is an activity row whose purpose is `income` and obligations whose source is `shared_income`:
the CHECKs learn the words. Downgrading turns them into advances (the entries and what they left owed stay as they are).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4e6f8a0c2d5"
down_revision: str | Sequence[str] | None = "a3d5f7b9c1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES = "'loan', 'borrowing', 'advance', 'gift', 'expense', 'settlement', 'opening', 'netoff'"
SOURCES = "'shared_expense', 'loan', 'borrowing', 'advance', 'opening'"


def _checks(purposes: str, sources: str) -> None:
    with op.batch_alter_table("party_transactions") as batch:
        batch.drop_constraint("ck_party_transactions_purpose", type_="check")
        batch.create_check_constraint("ck_party_transactions_purpose", f"purpose IN ({purposes})")
    with op.batch_alter_table("party_obligations") as batch:
        batch.drop_constraint("ck_party_obligations_source", type_="check")
        batch.create_check_constraint("ck_party_obligations_source", f"source_type IN ({sources})")


def upgrade() -> None:
    _checks(f"{PURPOSES}, 'income'", f"{SOURCES}, 'shared_income'")


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE party_obligations SET source_type = 'advance' WHERE source_type = 'shared_income'"))
    conn.execute(sa.text("UPDATE party_transactions SET purpose = 'advance' WHERE purpose = 'income'"))
    _checks(PURPOSES, SOURCES)
