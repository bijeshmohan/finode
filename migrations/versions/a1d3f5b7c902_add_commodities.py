"""add commodities: accounts hold a commodity, transactions a currency, postings a value

Revision ID: a1d3f5b7c902
Revises: 9c2d4e6f1a51
Create Date: 2026-10-05 00:00:00.000000

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.commodity_seed import DEFAULT_CURRENCY_CODE, seed_id, seed_rows


# revision identifiers, used by Alembic.
revision: str = 'a1d3f5b7c902'
down_revision: Union[str, Sequence[str], None] = '9c2d4e6f1a51'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    commodities = op.create_table(
        "commodities",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("decimals", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=8), nullable=True),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("cid"),
    )
    op.create_index(op.f("ix_commodities_user"), "commodities", ["user"], unique=False)
    op.create_index(
        "uq_commodities_global_code",
        "commodities",
        ["code"],
        unique=True,
        sqlite_where=sa.text('"user" IS NULL'),
        postgresql_where=sa.text('"user" IS NULL'),
    )
    op.create_index(
        "uq_commodities_user_code",
        "commodities",
        ["user", "code"],
        unique=True,
        sqlite_where=sa.text('"user" IS NOT NULL'),
        postgresql_where=sa.text('"user" IS NOT NULL'),
    )
    op.bulk_insert(commodities, seed_rows(datetime.now(timezone.utc)))

    # Everything recorded so far is in the default currency.
    inr = seed_id(DEFAULT_CURRENCY_CODE)

    def fill(statement: str) -> None:
        op.execute(sa.text(statement).bindparams(sa.bindparam("inr", value=inr, type_=sa.Uuid())))

    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.add_column(sa.Column("default_commodity_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key("fk_profiles_default_commodity", "commodities", ["default_commodity_id"], ["cid"])
    fill("UPDATE profiles SET default_commodity_id = :inr")

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("commodity_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key("fk_accounts_commodity", "commodities", ["commodity_id"], ["cid"])
    # Root accounts hold nothing of their own.
    fill("UPDATE accounts SET commodity_id = :inr WHERE parent_id IS NOT NULL")

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("currency_id", sa.Uuid(), nullable=True))
    fill("UPDATE transactions SET currency_id = :inr")
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.alter_column("currency_id", existing_type=sa.Uuid(), nullable=False)
        batch_op.create_foreign_key("fk_transactions_currency", "commodities", ["currency_id"], ["cid"])

    with op.batch_alter_table("postings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("value", sa.Numeric(24, 8), nullable=True))
    op.execute("UPDATE postings SET value = amount")
    with op.batch_alter_table("postings", schema=None) as batch_op:
        batch_op.alter_column("value", existing_type=sa.Numeric(24, 8), nullable=False)
        batch_op.alter_column(
            "amount", existing_type=sa.Numeric(12, 2), type_=sa.Numeric(24, 8), existing_nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("postings", schema=None) as batch_op:
        batch_op.alter_column(
            "amount", existing_type=sa.Numeric(24, 8), type_=sa.Numeric(12, 2), existing_nullable=False
        )
        batch_op.drop_column("value")

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_transactions_currency", type_="foreignkey")
        batch_op.drop_column("currency_id")

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_constraint("fk_accounts_commodity", type_="foreignkey")
        batch_op.drop_column("commodity_id")

    with op.batch_alter_table("profiles", schema=None) as batch_op:
        batch_op.drop_constraint("fk_profiles_default_commodity", type_="foreignkey")
        batch_op.drop_column("default_commodity_id")

    op.drop_index("uq_commodities_user_code", table_name="commodities")
    op.drop_index("uq_commodities_global_code", table_name="commodities")
    op.drop_index(op.f("ix_commodities_user"), table_name="commodities")
    op.drop_table("commodities")
