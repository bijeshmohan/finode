"""personal access tokens for the MCP server; where each transaction was entered and changed

Revision ID: d6b8c0e2f347
Revises: c4a6b8d0e135
Create Date: 2026-10-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6b8c0e2f347'
down_revision: Union[str, Sequence[str], None] = 'c4a6b8d0e135'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tkid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("scope", sa.String(length=10), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("last_used", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('read', 'write')", name="ck_api_tokens_scope"),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("tkid"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_api_tokens_user"), "api_tokens", ["user"], unique=False)

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("created_via", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("updated_via", sa.String(length=60), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_column("updated_via")
        batch_op.drop_column("created_via")
    op.drop_index(op.f("ix_api_tokens_user"), table_name="api_tokens")
    op.drop_table("api_tokens")
