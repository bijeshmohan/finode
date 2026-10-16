"""one currency for the whole ledger: no commodities, assets or prices

Revision ID: f4b6d8a0c2e5
Revises: e2a4c6e8f1b3
Create Date: 2026-10-17 00:00:00.000000

Every person keeps their ledger in one currency, now a column on the profile. The migration refuses to run
(and changes nothing) when somebody recorded anything that cannot be kept that way: assets of their own,
prices, accounts or transactions in more than one currency, or conversions. There is no way back.
"""
from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4b6d8a0c2e5'
down_revision: Union[str, Sequence[str], None] = 'e2a4c6e8f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT = "INR"


def _uuid(value) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _count(connection, sql: str) -> int:
    return connection.execute(sa.text(sql)).scalar() or 0


def _currencies(connection) -> dict:
    """The one currency each person's ledger is in (the profile's choice when it holds nothing yet)."""
    used: dict = {}
    for sql in (
        "SELECT a.\"user\", c.code FROM accounts a JOIN commodities c ON c.cid = a.commodity_id",
        "SELECT t.\"user\", c.code FROM transactions t JOIN commodities c ON c.cid = t.currency_id",
    ):
        for user, code in connection.execute(sa.text(sql)):
            used.setdefault(_uuid(user), set()).add(code)
    chosen: dict = {}
    for user, code in connection.execute(
        sa.text("SELECT p.\"user\", c.code FROM profiles p LEFT JOIN commodities c ON c.cid = p.default_commodity_id")
    ):
        chosen[_uuid(user)] = code or DEFAULT
    result: dict = {}
    for user in set(used) | set(chosen):
        codes = used.get(user, set())
        if len(codes) > 1:
            raise RuntimeError(
                f"a ledger uses more than one currency ({', '.join(sorted(codes))}): finode now keeps one currency per "
                "person. Move everything into one currency before migrating."
            )
        result[user] = next(iter(codes)) if codes else chosen.get(user, DEFAULT)
    return result


def upgrade() -> None:
    connection = op.get_bind()
    if _count(connection, 'SELECT count(*) FROM commodities WHERE "user" IS NOT NULL'):
        raise RuntimeError("somebody has assets of their own (stocks, funds, coins): remove them before migrating")
    if _count(connection, "SELECT count(*) FROM prices"):
        raise RuntimeError("prices were entered: remove them before migrating")
    if _count(connection, "SELECT count(*) FROM postings WHERE amount <> value"):
        raise RuntimeError("some postings are conversions between commodities: remove them before migrating")
    if _count(connection, "SELECT count(*) FROM recurring_transactions WHERE received_amount IS NOT NULL") or _count(
        connection, "SELECT count(*) FROM recurring_postings WHERE value IS NOT NULL AND value <> amount"
    ):
        raise RuntimeError("some recurring rules convert between commodities: remove them before migrating")
    currencies = _currencies(connection)

    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("currency", sa.String(length=3), nullable=False, server_default=DEFAULT))
    now = datetime.now(timezone.utc)
    profiles = {_uuid(row[0]) for row in connection.execute(sa.text('SELECT "user" FROM profiles'))}
    for user, code in currencies.items():
        if user in profiles:
            connection.execute(
                sa.text('UPDATE profiles SET currency = :code WHERE "user" = :user').bindparams(
                    sa.bindparam("code", code), sa.bindparam("user", user, type_=sa.Uuid())
                )
            )
        elif code != DEFAULT:
            connection.execute(
                sa.text('INSERT INTO profiles ("user", currency, created, updated) VALUES (:user, :code, :now, :now)').bindparams(
                    sa.bindparam("code", code),
                    sa.bindparam("user", user, type_=sa.Uuid()),
                    sa.bindparam("now", now, type_=sa.DateTime(timezone=True)),
                )
            )

    with op.batch_alter_table("profiles") as batch:
        batch.drop_constraint("fk_profiles_default_commodity", type_="foreignkey")
        batch.drop_column("default_commodity_id")
    with op.batch_alter_table("accounts") as batch:
        batch.drop_constraint("fk_accounts_commodity", type_="foreignkey")
        batch.drop_column("commodity_id")
    with op.batch_alter_table("transactions") as batch:
        batch.drop_constraint("fk_transactions_currency", type_="foreignkey")
        batch.drop_column("currency_id")
    with op.batch_alter_table("postings") as batch:
        batch.drop_constraint("ck_postings_value_positive", type_="check")
        batch.drop_column("value")
    with op.batch_alter_table("recurring_transactions") as batch:
        batch.drop_column("currency")
        batch.drop_column("received_amount")
    with op.batch_alter_table("recurring_postings") as batch:
        batch.drop_column("value")

    op.drop_table("prices")
    op.drop_table("commodities")


def downgrade() -> None:
    raise RuntimeError("the single-currency migration cannot be undone: restore a backup taken before it instead")
