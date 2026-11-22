"""every account of the four types is in the budget: drop accounts.on_budget and new_accounts_in_budget

Revision ID: f9b1d3e5a7c0
Revises: e8a0c2d4f6b9
Create Date: 2026-11-22 18:00:00.000000

Whether an account is part of the budget is its type now (services/account_types.py), so the flag and a group's
choice for its accounts go. It refuses to run, changing nothing, while a person's books are not in the four types yet
(Investments, Loans, a group of their own, an account straight under Assets or Liabilities that is not a person's):
convert them first with `python -m finode.commands.cash_flow`. The downgrade adds both back as the types say.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f9b1d3e5a7c0"
down_revision: str | Sequence[str] | None = "e8a0c2d4f6b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES = ("assets.bank", "assets.cash", "liabilities.cards", "assets.wallet")
RETIRED = ("assets.investments", "liabilities.loans")


def upgrade() -> None:
    connection = op.get_bind()
    left = connection.execute(
        sa.text(
            "SELECT a.name FROM accounts a JOIN accounts root ON root.id = a.parent_id "
            "WHERE root.parent_id IS NULL AND root.name IN ('Assets', 'Liabilities') "
            "AND (a.system_key IS NULL OR a.system_key IN :retired) "
            "AND a.id NOT IN (SELECT account_id FROM contact_accounts)"
        ).bindparams(sa.bindparam("retired", expanding=True)),
        {"retired": list(RETIRED)},
    ).all()
    if left:
        names = ", ".join(sorted({row[0] for row in left}))
        raise RuntimeError(
            f"convert the books first (python -m finode.commands.cash_flow): not in the four types yet: {names}"
        )
    with op.batch_alter_table("accounts") as batch:
        batch.drop_column("on_budget")
        batch.drop_column("new_accounts_in_budget")


def downgrade() -> None:
    op.add_column("accounts", sa.Column("on_budget", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("accounts", sa.Column("new_accounts_in_budget", sa.Boolean(), nullable=True))
    types = sa.bindparam("types", expanding=True)
    op.get_bind().execute(
        sa.text(
            "UPDATE accounts SET on_budget = :yes WHERE parent_id IN (SELECT id FROM accounts WHERE system_key IN :types)"
        ).bindparams(types),
        {"yes": True, "types": list(TYPES)},
    )
    op.get_bind().execute(
        sa.text("UPDATE accounts SET new_accounts_in_budget = :yes WHERE system_key IN :types").bindparams(
            sa.bindparam("types", expanding=True)
        ),
        {"yes": True, "types": list(TYPES)},
    )
