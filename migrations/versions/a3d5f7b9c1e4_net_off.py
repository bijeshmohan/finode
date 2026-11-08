"""Contacts: netting off what two people owe each other

Revision ID: a3d5f7b9c1e4
Revises: f1b3d5e7a9c6
Create Date: 2026-11-08 12:00:00.000000

A net off is an activity row whose purpose is `netoff`: the CHECK learns the word. Downgrading turns them into
settlements (the entries and what they cleared stay as they are).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d5f7b9c1e4"
down_revision: str | Sequence[str] | None = "f1b3d5e7a9c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURPOSES = "'loan', 'borrowing', 'advance', 'gift', 'expense', 'settlement', 'opening'"


def _check(purposes: str) -> None:
    with op.batch_alter_table("party_transactions") as batch:
        batch.drop_constraint("ck_party_transactions_purpose", type_="check")
        batch.create_check_constraint("ck_party_transactions_purpose", f"purpose IN ({purposes})")


def upgrade() -> None:
    _check(f"{PURPOSES}, 'netoff'")


def downgrade() -> None:
    op.get_bind().execute(sa.text("UPDATE party_transactions SET purpose = 'settlement' WHERE purpose = 'netoff'"))
    _check(PURPOSES)
