"""A loan's usual category for payments is gone: nothing is filled in for the person

Revision ID: c6e8a0b2d4f7
Revises: b4d6f8a0c2e5
Create Date: 2026-11-01 12:00:00.000000

`accounts.payment_category_id` (the category a payment into a loan or fund was labelled with when none was chosen) is
dropped, with its foreign key. A payment keeps the label it already has: lines are not touched, so the budget, the
reports and the Categories page read exactly what they read before. From now on a payment into a loan carries a category
only when the person (or an assistant, or a recurring rule) gives one, and the bell lists the ones that have none.

The downgrade adds the column back, empty: the settings that were in it are not restored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6e8a0b2d4f7"
down_revision: str | Sequence[str] | None = "b4d6f8a0c2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("fk_accounts_payment_category", type_="foreignkey")
        batch.drop_column("payment_category_id")


def downgrade() -> None:
    with op.batch_alter_table("accounts") as batch:
        batch.add_column(sa.Column("payment_category_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_accounts_payment_category", "budget_categories", ["payment_category_id"], ["id"])
