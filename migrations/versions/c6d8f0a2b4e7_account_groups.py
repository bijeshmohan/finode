"""A group is its own kind of account: it says whether the accounts made in it start in the budget

Revision ID: c6d8f0a2b4e7
Revises: b4e6f8a0c2d5
Create Date: 2026-11-10 12:00:00.000000

`accounts.new_accounts_in_budget` is set on a group (and empty on every other account), so a group can exist before it has
accounts in it. The built-in groups get what the code used to hold for them: a bank, cash and a card start in the budget,
investments and loans outside it. Groups that only exist because an account was made inside another account are left as
they are (empty), and keep the type's default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d8f0a2b4e7"
down_revision: str | Sequence[str] | None = "b4e6f8a0c2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STARTS = {
    "assets.bank": True,
    "assets.cash": True,
    "assets.investments": False,
    "liabilities.cards": True,
    "liabilities.loans": False,
}


def upgrade() -> None:
    op.add_column("accounts", sa.Column("new_accounts_in_budget", sa.Boolean(), nullable=True))
    accounts = sa.table("accounts", sa.column("system_key", sa.String), sa.column("new_accounts_in_budget", sa.Boolean))
    for key, start in STARTS.items():
        op.execute(accounts.update().where(accounts.c.system_key == key).values(new_accounts_in_budget=start))


def downgrade() -> None:
    op.drop_column("accounts", "new_accounts_in_budget")
