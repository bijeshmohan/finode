"""what each user let each OAuth app (AI assistant) do

Revision ID: e8d0f2a4b569
Revises: d6b8c0e2f347
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8d0f2a4b569'
down_revision: Union[str, Sequence[str], None] = 'd6b8c0e2f347'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_grants",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=False),
        sa.Column("client_name", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('read', 'write')", name="ck_oauth_grants_scope"),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("gid"),
    )
    op.create_index(op.f("ix_oauth_grants_user"), "oauth_grants", ["user"], unique=False)
    op.create_index("uq_oauth_grants_user_client", "oauth_grants", ["user", "client_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_oauth_grants_user_client", table_name="oauth_grants")
    op.drop_index(op.f("ix_oauth_grants_user"), table_name="oauth_grants")
    op.drop_table("oauth_grants")
