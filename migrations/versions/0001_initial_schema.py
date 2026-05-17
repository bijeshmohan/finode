"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


transaction_type = sa.Enum("INCOME", "EXPENSE", "TRANSFER", name="type")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "accounts",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.Column("details", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.Column("balance", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("aid"),
    )
    op.create_index("ix_accounts_user", "accounts", ["user"], unique=False)

    op.create_table(
        "categories",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("type", transaction_type, nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("cid"),
    )
    op.create_index("ix_categories_user", "categories", ["user"], unique=False)

    op.create_table(
        "transactions",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("source", sa.Uuid(), nullable=True),
        sa.Column("destination", sa.Uuid(), nullable=True),
        sa.Column("category", sa.Uuid(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=True),
        sa.Column("details", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.ForeignKeyConstraint(["category"], ["categories.cid"]),
        sa.ForeignKeyConstraint(["destination"], ["accounts.aid"]),
        sa.ForeignKeyConstraint(["source"], ["accounts.aid"]),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("tid"),
    )
    op.create_index("ix_transactions_user", "transactions", ["user"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_transactions_user", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_categories_user", table_name="categories")
    op.drop_table("categories")
    op.drop_index("ix_accounts_user", table_name="accounts")
    op.drop_table("accounts")
    transaction_type.drop(op.get_bind(), checkfirst=True)
