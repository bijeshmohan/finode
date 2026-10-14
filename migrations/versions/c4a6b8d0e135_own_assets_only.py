"""built-in currencies are the full ISO 4217 list; all other commodities and every price are the user's own

Revision ID: c4a6b8d0e135
Revises: b2e4a6c8d013
Create Date: 2026-10-06 00:00:00.000000

"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import UUID, uuid4

from alembic import op
import sqlalchemy as sa

from app.commodity_seed import seed_rows


# revision identifiers, used by Alembic.
revision: str = 'c4a6b8d0e135'
down_revision: Union[str, Sequence[str], None] = 'b2e4a6c8d013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Rows of the old shared catalog that are not currencies.
OLD_SHARED_ASSETS = ("BTC", "ETH", "USDT", "USDC")

# Uses of a commodity: (table, column).
REFERENCES = (
    ("accounts", "commodity_id"),
    ("transactions", "currency_id"),
    ("prices", "commodity_id"),
    ("prices", "quote_id"),
)


def upgrade() -> None:
    bind = op.get_bind()
    commodities = sa.table(
        "commodities",
        sa.column("created", sa.DateTime(timezone=True)),
        sa.column("updated", sa.DateTime(timezone=True)),
        sa.column("cid", sa.Uuid()),
        sa.column("user", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("decimals", sa.Integer()),
        sa.column("symbol", sa.String()),
    )
    now = datetime.now(timezone.utc)

    # 1. The rest of the ISO currencies.
    have = {row[0] for row in bind.execute(sa.text("SELECT code FROM commodities WHERE \"user\" IS NULL"))}
    missing = [row for row in seed_rows(now) if row["code"] not in have]
    if missing:
        # A user's own commodity may already use one of the new codes: a code names one thing.
        clash = bind.execute(
            sa.text("SELECT code FROM commodities WHERE \"user\" IS NOT NULL AND code IN :codes").bindparams(
                sa.bindparam("codes", expanding=True)
            ),
            {"codes": [row["code"] for row in missing]},
        ).fetchall()
        if clash:
            raise RuntimeError(
                "rename these commodities before upgrading, they are now built-in currency codes: "
                + ", ".join(sorted({row[0] for row in clash}))
            )
        op.bulk_insert(commodities, missing)

    # 2. Shared non-currency rows become private copies for the users who use them.
    shared = bind.execute(
        sa.text('SELECT cid, code, name, kind, decimals, symbol FROM commodities WHERE "user" IS NULL AND kind <> \'currency\'')
    ).fetchall()
    for raw_cid, code, name, kind, decimals, symbol in shared:
        cid = UUID(str(raw_cid))  # SQLite hands ids back as text
        users = set()
        for table, column in REFERENCES:
            owner = 't."user"'
            users |= {
                UUID(str(row[0]))
                for row in bind.execute(
                    sa.text(f'SELECT DISTINCT {owner} FROM {table} t WHERE t.{column} = :cid AND {owner} IS NOT NULL').bindparams(
                        sa.bindparam("cid", type_=sa.Uuid())
                    ),
                    {"cid": cid},
                )
            }
        for user in users:
            copy = uuid4()
            bind.execute(
                sa.insert(commodities).values(
                    created=now, updated=now, cid=copy, user=user, code=code, name=name,
                    kind=kind, decimals=decimals, symbol=symbol,
                )
            )
            for table, column in REFERENCES:
                bind.execute(
                    sa.text(f'UPDATE {table} SET {column} = :copy WHERE {column} = :cid AND "user" = :user').bindparams(
                        sa.bindparam("copy", type_=sa.Uuid()), sa.bindparam("cid", type_=sa.Uuid()), sa.bindparam("user", type_=sa.Uuid())
                    ),
                    {"copy": copy, "cid": cid, "user": user},
                )

    # 3. There is no shared price feed any more.
    op.execute('DELETE FROM prices WHERE "user" IS NULL')
    op.execute(
        sa.text("DELETE FROM commodities WHERE \"user\" IS NULL AND kind <> 'currency'")
    )
    op.drop_index("uq_prices_global", table_name="prices")
    with op.batch_alter_table("prices", schema=None) as batch_op:
        batch_op.alter_column("user", existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    # The extra currencies and the private copies stay; only the shared-feed shape returns.
    with op.batch_alter_table("prices", schema=None) as batch_op:
        batch_op.alter_column("user", existing_type=sa.Uuid(), nullable=True)
    op.create_index(
        "uq_prices_global",
        "prices",
        ["commodity_id", "quote_id", "date"],
        unique=True,
        sqlite_where=sa.text('"user" IS NULL'),
        postgresql_where=sa.text('"user" IS NULL'),
    )
