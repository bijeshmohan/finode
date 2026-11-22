"""each person orders the four account types: profiles.account_type_order

Revision ID: e8a0c2d4f6b9
Revises: d7e9a1c3b5f8
Create Date: 2026-11-22 12:00:00.000000

Every account is one of four types now (Bank Account, Cash, Credit Card, Prepaid Wallet). The person puts them in their
own order, which the Accounts page, the pickers and the assistants follow; everyone starts with the order below.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8a0c2d4f6b9"
down_revision: str | Sequence[str] | None = "d7e9a1c3b5f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STARTING_ORDER = "assets.bank,assets.cash,liabilities.cards,assets.wallet"


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("account_type_order", sa.String(length=80), nullable=False, server_default=STARTING_ORDER),
    )


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("account_type_order")
