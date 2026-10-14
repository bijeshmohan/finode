"""add prices

Revision ID: b2e4a6c8d013
Revises: a1d3f5b7c902
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2e4a6c8d013'
down_revision: Union[str, Sequence[str], None] = 'a1d3f5b7c902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "prices",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=True),
        sa.Column("commodity_id", sa.Uuid(), nullable=False),
        sa.Column("quote_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(28, 12), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.ForeignKeyConstraint(["commodity_id"], ["commodities.cid"]),
        sa.ForeignKeyConstraint(["quote_id"], ["commodities.cid"]),
        sa.PrimaryKeyConstraint("pid"),
        sa.CheckConstraint("price > 0", name="ck_prices_positive"),
    )
    op.create_index(op.f("ix_prices_user"), "prices", ["user"], unique=False)
    op.create_index(
        "uq_prices_global",
        "prices",
        ["commodity_id", "quote_id", "date"],
        unique=True,
        sqlite_where=sa.text('"user" IS NULL'),
        postgresql_where=sa.text('"user" IS NULL'),
    )
    op.create_index(
        "uq_prices_user",
        "prices",
        ["user", "commodity_id", "quote_id", "date"],
        unique=True,
        sqlite_where=sa.text('"user" IS NOT NULL'),
        postgresql_where=sa.text('"user" IS NOT NULL'),
    )


def downgrade() -> None:
    op.drop_index("uq_prices_user", table_name="prices")
    op.drop_index("uq_prices_global", table_name="prices")
    op.drop_index(op.f("ix_prices_user"), table_name="prices")
    op.drop_table("prices")
