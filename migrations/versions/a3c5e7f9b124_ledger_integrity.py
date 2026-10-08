"""ledger integrity: posting checks and transaction history

Revision ID: a3c5e7f9b124
Revises: f1a3c5e7b892
Create Date: 2026-10-08 00:00:00.000000

"""
from decimal import Decimal
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3c5e7f9b124'
down_revision: Union[str, Sequence[str], None] = 'f1a3c5e7b892'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bad = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM postings WHERE amount <= 0 OR value <= 0 OR side NOT IN ('DEBIT', 'CREDIT')"
        )
    ).scalar()
    if bad:
        raise RuntimeError(f"{bad} posting(s) are not positive or have an unknown side: fix them before migrating")
    with op.batch_alter_table("postings") as batch:
        batch.create_check_constraint("ck_postings_amount_positive", "amount > 0")
        batch.create_check_constraint("ck_postings_value_positive", "value > 0")
        batch.create_check_constraint("ck_postings_side", "side IN ('DEBIT', 'CREDIT')")

    history = op.create_table(
        "transaction_history",
        sa.Column("hid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("via", sa.String(length=60), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.CheckConstraint("action IN ('created', 'updated', 'deleted')", name="ck_transaction_history_action"),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("hid"),
    )
    op.create_index(op.f("ix_transaction_history_user"), "transaction_history", ["user"], unique=False)
    op.create_index("ix_transaction_history_user_transaction", "transaction_history", ["user", "transaction_id"])

    # Every transaction that exists starts its history as it is now.
    connection = op.get_bind()
    postings_table = sa.table(
        "postings",
        sa.column("transaction", sa.Uuid()),
        sa.column("account", sa.Uuid()),
        sa.column("side", sa.String()),
        sa.column("amount", sa.Numeric(24, 8)),
        sa.column("value", sa.Numeric(24, 8)),
        sa.column("created", sa.DateTime(timezone=True)),
        sa.column("pid", sa.Uuid()),
    )
    transactions_table = sa.table(
        "transactions",
        sa.column("tid", sa.Uuid()),
        sa.column("user", sa.Uuid()),
        sa.column("date", sa.Date()),
        sa.column("payee", sa.String()),
        sa.column("comment", sa.String()),
        sa.column("currency_id", sa.Uuid()),
        sa.column("recurring_id", sa.Uuid()),
        sa.column("created_via", sa.String()),
        sa.column("created", sa.DateTime(timezone=True)),
    )
    postings: dict = {}
    for row in connection.execute(
        sa.select(
            postings_table.c.transaction,
            postings_table.c.account,
            postings_table.c.side,
            postings_table.c.amount,
            postings_table.c.value,
        ).order_by(postings_table.c.created, postings_table.c.pid)
    ):
        postings.setdefault(row[0], []).append(
            {"account": str(row[1]), "side": str(row[2]).lower(), "amount": _plain(row[3]), "value": _plain(row[4])}
        )
    rows = []
    for t in connection.execute(sa.select(*transactions_table.c)):
        rows.append(
            {
                "hid": uuid4(),
                "user": t.user,
                "transaction_id": t.tid,
                "action": "created",
                "at": t.created,
                "via": t.created_via,
                "snapshot": {
                    "date": t.date.isoformat(),
                    "payee": t.payee,
                    "comment": t.comment,
                    "currency_id": str(t.currency_id),
                    "recurring_id": str(t.recurring_id) if t.recurring_id else None,
                    "postings": postings.get(t.tid, []),
                },
            }
        )
    if rows:
        op.bulk_insert(history, rows)


def _plain(value: Decimal) -> str:
    """100.00000000 -> 100.00, 0.01250000 -> 0.0125 (the way the app reads amounts)."""
    value = Decimal(value)
    places = max(2, -value.normalize().as_tuple().exponent)
    return str(value.quantize(Decimal(1).scaleb(-places)))


def downgrade() -> None:
    op.drop_index("ix_transaction_history_user_transaction", table_name="transaction_history")
    op.drop_index(op.f("ix_transaction_history_user"), table_name="transaction_history")
    op.drop_table("transaction_history")
    with op.batch_alter_table("postings") as batch:
        batch.drop_constraint("ck_postings_side", type_="check")
        batch.drop_constraint("ck_postings_value_positive", type_="check")
        batch.drop_constraint("ck_postings_amount_positive", type_="check")
