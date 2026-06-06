"""double entry ledger

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06 00:00:00.000000

"""
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid(connection):
    value = uuid4()
    if connection.dialect.name == "sqlite":
        return value.hex
    return value


def _type_value(value) -> str:
    value = str(value)
    if "." in value:
        value = value.rsplit(".", 1)[1]
    return value.lower()


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "type",
                sqlmodel.sql.sqltypes.AutoString(length=20),
                nullable=False,
                server_default="asset",
            )
        )
        batch_op.create_index("ix_accounts_type", ["type"], unique=False)

    op.create_table(
        "journal_entries",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("jid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("note", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=True),
        sa.Column("details", sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("jid"),
    )
    op.create_index("ix_journal_entries_user", "journal_entries", ["user"], unique=False)

    op.create_table(
        "journal_lines",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("entry", sa.Uuid(), nullable=False),
        sa.Column("account", sa.Uuid(), nullable=False),
        sa.Column("side", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(["account"], ["accounts.aid"]),
        sa.ForeignKeyConstraint(["entry"], ["journal_entries.jid"]),
        sa.ForeignKeyConstraint(["user"], ["auth.users.id"]),
        sa.PrimaryKeyConstraint("lid"),
    )
    op.create_index("ix_journal_lines_account", "journal_lines", ["account"], unique=False)
    op.create_index("ix_journal_lines_entry", "journal_lines", ["entry"], unique=False)
    op.create_index("ix_journal_lines_user", "journal_lines", ["user"], unique=False)

    connection = op.get_bind()
    metadata = sa.MetaData()
    accounts = sa.Table("accounts", metadata, autoload_with=connection)
    categories = sa.Table("categories", metadata, autoload_with=connection)
    transactions = sa.Table("transactions", metadata, autoload_with=connection)
    journal_entries = sa.Table("journal_entries", metadata, autoload_with=connection)
    journal_lines = sa.Table("journal_lines", metadata, autoload_with=connection)

    category_accounts = {}
    uncategorized_accounts = {}
    opening_accounts = {}

    def create_account(user, name: str, account_type: str, details: str | None = None):
        aid = _uuid(connection)
        timestamp = _now()
        connection.execute(
            accounts.insert().values(
                created=timestamp,
                updated=timestamp,
                aid=aid,
                user=user,
                name=name,
                details=details,
                balance=Decimal("0.00"),
                type=account_type,
            )
        )
        return aid

    def uncategorized_account(user, account_type: str):
        key = (user, account_type)
        if key not in uncategorized_accounts:
            uncategorized_accounts[key] = create_account(
                user,
                f"Uncategorized {account_type.title()}",
                account_type,
                "System account for migrated uncategorized transactions",
            )
        return uncategorized_accounts[key]

    def opening_account(user):
        if user not in opening_accounts:
            opening_accounts[user] = create_account(
                user,
                "Opening Balances",
                "equity",
                "System account for opening balance adjustments",
            )
        return opening_accounts[user]

    def create_entry(user, txn_date, note, details, lines):
        timestamp = _now()
        jid = _uuid(connection)
        connection.execute(
            journal_entries.insert().values(
                created=timestamp,
                updated=timestamp,
                jid=jid,
                user=user,
                date=txn_date or date.today(),
                note=note,
                details=details,
            )
        )
        for account_id, side, amount in lines:
            connection.execute(
                journal_lines.insert().values(
                    created=timestamp,
                    updated=timestamp,
                    lid=_uuid(connection),
                    user=user,
                    entry=jid,
                    account=account_id,
                    side=side,
                    amount=amount,
                )
            )
        return jid

    for category in connection.execute(sa.select(categories)).mappings():
        category_type = _type_value(category["type"])
        if category_type not in ("income", "expense"):
            continue
        category_accounts[category["cid"]] = create_account(
            category["user"],
            category["name"],
            category_type,
            "Migrated category account",
        )

    running_balances = {}
    for transaction in connection.execute(sa.select(transactions)).mappings():
        user = transaction["user"]
        amount = transaction["amount"]
        source = transaction["source"]
        destination = transaction["destination"]
        category = transaction["category"]
        lines = []

        if source is not None and destination is not None:
            lines = [
                (destination, "debit", amount),
                (source, "credit", amount),
            ]
            running_balances[destination] = running_balances.get(destination, Decimal("0.00")) + amount
            running_balances[source] = running_balances.get(source, Decimal("0.00")) - amount
        elif source is not None:
            expense_account = category_accounts.get(category) or uncategorized_account(user, "expense")
            lines = [
                (expense_account, "debit", amount),
                (source, "credit", amount),
            ]
            running_balances[source] = running_balances.get(source, Decimal("0.00")) - amount
        elif destination is not None:
            income_account = category_accounts.get(category) or uncategorized_account(user, "income")
            lines = [
                (destination, "debit", amount),
                (income_account, "credit", amount),
            ]
            running_balances[destination] = running_balances.get(destination, Decimal("0.00")) + amount
        else:
            continue

        create_entry(
            user,
            transaction["date"],
            transaction["note"],
            transaction["details"],
            lines,
        )

    for account in connection.execute(sa.select(accounts)).mappings():
        desired = account["balance"] or Decimal("0.00")
        current = running_balances.get(account["aid"], Decimal("0.00"))
        difference = desired - current
        if difference == 0:
            continue
        if difference > 0:
            lines = [
                (account["aid"], "debit", abs(difference)),
                (opening_account(account["user"]), "credit", abs(difference)),
            ]
        else:
            lines = [
                (account["aid"], "credit", abs(difference)),
                (opening_account(account["user"]), "debit", abs(difference)),
            ]
        create_entry(
            account["user"],
            date.today(),
            "Opening balance",
            "Migrated stored account balance",
            lines,
        )

    op.drop_index("ix_transactions_user", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_categories_user", table_name="categories")
    op.drop_table("categories")

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.drop_column("balance")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "categories",
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cid", sa.Uuid(), nullable=False),
        sa.Column("user", sa.Uuid(), nullable=False),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=False),
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

    with op.batch_alter_table("accounts") as batch_op:
        batch_op.add_column(
            sa.Column(
                "balance",
                sa.Numeric(precision=12, scale=2),
                nullable=False,
                server_default="0.00",
            )
        )
        batch_op.drop_index("ix_accounts_type")
        batch_op.drop_column("type")

    op.drop_index("ix_journal_lines_user", table_name="journal_lines")
    op.drop_index("ix_journal_lines_entry", table_name="journal_lines")
    op.drop_index("ix_journal_lines_account", table_name="journal_lines")
    op.drop_table("journal_lines")
    op.drop_index("ix_journal_entries_user", table_name="journal_entries")
    op.drop_table("journal_entries")
